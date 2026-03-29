#!/usr/bin/env python3
"""
zrktex — LaTeX editor
  python zrktex.py [file.tex]               GUI  (default)
  python zrktex.py --tui [file.tex]         TUI  (vim-like)
  python zrktex.py --plots [file.tex]       GUI + interactive plot viewer
"""

import subprocess, sys, os, re, shutil, threading, hashlib, json as _json, webbrowser, urllib.parse
from pathlib import Path
from copy import deepcopy
from enum import Enum
from typing import List, Tuple, Optional

# ══════════════════════════════════════════════════════════════════════════════
#  AUTO-INSTALL
# ══════════════════════════════════════════════════════════════════════════════
_TUI_MODE   = "--tui"   in sys.argv
_PLOTS_MODE = "--plots" in sys.argv

# Silently installs a package if it's missing — imp lets us handle cases
# where the pip name differs from the import name (e.g. "Pillow" vs "PIL")
def _ensure(pkg, imp=None):
    try:
        __import__(imp or pkg)
    except ImportError:
        print(f"Installing {pkg}…", flush=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg],
                              stdout=subprocess.DEVNULL)

_ensure("pygments")
_ensure("matplotlib")
_ensure("numpy")
if _TUI_MODE:
    if sys.platform == "win32":
        _ensure("windows-curses")
else:
    _ensure("Pillow", "PIL")
    _ensure("PyMuPDF", "fitz")

# ══════════════════════════════════════════════════════════════════════════════
#  SHARED IMPORTS
# ══════════════════════════════════════════════════════════════════════════════
try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend — we're saving to files, not showing windows
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    from mpl_toolkits.mplot3d import Axes3D  # noqa: registers projection
    import numpy as np
    HAS_MPL = True
except Exception:
    HAS_MPL = False

if not _TUI_MODE:
    try:
        from PIL import Image, ImageTk
        HAS_PIL = True
    except Exception:
        HAS_PIL = False

    try:
        import fitz
        HAS_FITZ = True
    except Exception:
        HAS_FITZ = False

try:
    from pygments.lexers import TexLexer as _TexLex
    from pygments.token import Token
    _TEX_LEXER = _TexLex()
    HAS_PYG = True
except Exception:
    HAS_PYG = False
    _TEX_LEXER = None

# ══════════════════════════════════════════════════════════════════════════════
#  SHARED CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
LATEX_COMMANDS = sorted([
    r"\begin", r"\end", r"\documentclass", r"\usepackage",
    r"\textbf", r"\textit", r"\texttt", r"\textrm", r"\textsf",
    r"\emph", r"\underline", r"\text", r"\mbox",
    r"\section", r"\subsection", r"\subsubsection",
    r"\paragraph", r"\subparagraph", r"\chapter", r"\part", r"\appendix",
    r"\label", r"\ref", r"\eqref", r"\pageref", r"\nameref",
    r"\cite", r"\citep", r"\citet", r"\bibliography", r"\bibliographystyle",
    r"\includegraphics", r"\caption", r"\centering",
    r"\frac", r"\dfrac", r"\tfrac", r"\sqrt",
    r"\sum", r"\int", r"\iint", r"\iiint", r"\oint",
    r"\prod", r"\lim", r"\sup", r"\inf", r"\max", r"\min",
    r"\alpha", r"\beta", r"\gamma", r"\delta", r"\epsilon", r"\varepsilon",
    r"\zeta", r"\eta", r"\theta", r"\vartheta", r"\iota", r"\kappa",
    r"\lambda", r"\mu", r"\nu", r"\xi", r"\pi", r"\varpi",
    r"\rho", r"\sigma", r"\tau", r"\upsilon", r"\phi", r"\varphi",
    r"\chi", r"\psi", r"\omega",
    r"\Gamma", r"\Delta", r"\Theta", r"\Lambda", r"\Xi",
    r"\Pi", r"\Sigma", r"\Upsilon", r"\Phi", r"\Psi", r"\Omega",
    r"\left", r"\right", r"\middle",
    r"\big", r"\Big", r"\bigg", r"\Bigg",
    r"\vspace", r"\hspace", r"\noindent", r"\par", r"\hline",
    r"\item", r"\maketitle", r"\tableofcontents",
    r"\newpage", r"\clearpage", r"\pagebreak",
    r"\title", r"\author", r"\date", r"\today",
    r"\mathbf", r"\mathrm", r"\mathit", r"\mathcal", r"\mathbb", r"\mathfrak",
    r"\overline", r"\hat", r"\bar", r"\vec", r"\tilde", r"\dot", r"\ddot",
    r"\leq", r"\geq", r"\neq", r"\approx", r"\equiv", r"\sim",
    r"\cdot", r"\times", r"\div", r"\pm", r"\mp",
    r"\infty", r"\partial", r"\nabla", r"\forall", r"\exists",
    r"\in", r"\notin", r"\subset", r"\supset", r"\subseteq",
    r"\cup", r"\cap", r"\setminus", r"\emptyset",
    r"\rightarrow", r"\leftarrow", r"\leftrightarrow",
    r"\Rightarrow", r"\Leftarrow", r"\Leftrightarrow",
    r"\mapsto", r"\to", r"\gets",
    r"\uparrow", r"\downarrow",
    r"\ldots", r"\cdots", r"\vdots", r"\ddots", r"\qquad", r"\quad",
    r"\newcommand", r"\renewcommand", r"\newenvironment",
    r"\footnote", r"\input", r"\include",
    r"\tiny", r"\scriptsize", r"\footnotesize", r"\small",
    r"\normalsize", r"\large", r"\Large", r"\LARGE", r"\huge", r"\Huge",
    r"\color", r"\textcolor", r"\colorbox",
    r"\hfill", r"\vfill",
    r"\sin", r"\cos", r"\tan", r"\log", r"\ln", r"\exp",
    r"\binom", r"\pmod", r"\gcd",
    r"\verb", r"\index", r"\raggedleft", r"\raggedright",
    r"\plot",
])

PLOT_OPTION_KEYS = sorted([
    "alpha=", "button", "cmap=", "color=", "figheight=", "figwidth=",
    "grid=", "label=", "linewidth=", "samples=", "style=",
    "tmax=", "tmin=", "title=", "type=",
    "width=", "xlabel=", "xmax=", "xmin=",
    "ylabel=", "ymax=", "ymin=",
    "zlabel=", "zmax=", "zmin=",
])
PLOT_OPTION_VALUES: dict = {
    "type":  ["2d", "3d", "complex", "curve3d", "param", "parametric", "surface", "vector"],
    "style": ["quiver", "stream"],
    "cmap":  ["RdBu", "coolwarm", "hsv", "inferno", "magma", "plasma", "twilight", "viridis"],
    "grid":  ["false", "true"],
}


def _plot_option_context(line: str):
    """Return (prefix, candidates) when cursor is inside \\plot[...], else None."""
    if not re.search(r"\\plot\[", line):
        return None
    m = re.search(r"\\plot\[([^\]]*?)$", line)
    if not m:
        return None
    opts = m.group(1)
    # Value completion — after  key=partial
    vm = re.search(r"(\w+)=(\w*)$", opts)
    if vm:
        key, partial = vm.group(1), vm.group(2)
        vals = PLOT_OPTION_VALUES.get(key, [])
        return (partial, [v for v in vals if v.startswith(partial)])
    # Key completion — after comma / opening bracket
    km = re.search(r"(?:^|,\s*)(\w*)$", opts)
    if km:
        partial = km.group(1)
        return (partial, [k for k in PLOT_OPTION_KEYS if k.startswith(partial)])
    return ("", [])

ENVIRONMENTS = sorted([
    "document", "abstract",
    "equation", "equation*", "align", "align*", "aligned",
    "gather", "gather*", "multline", "split",
    "array", "matrix", "pmatrix", "bmatrix", "vmatrix", "Vmatrix", "cases",
    "figure", "figure*", "table", "table*",
    "tabular", "tabularx", "longtable",
    "itemize", "enumerate", "description",
    "theorem", "lemma", "corollary", "proof", "definition", "remark",
    "verbatim", "lstlisting",
    "minipage", "center", "flushleft", "flushright",
    "quote", "quotation",
    "thebibliography",
    "tikzpicture", "axis",
    "frame",
])

# ══════════════════════════════════════════════════════════════════════════════
#  PLOT PREPROCESSOR
# ══════════════════════════════════════════════════════════════════════════════
class PlotProcessor:
    """
    Replaces every  \\plot[options]{expression}  with \\includegraphics{}.

    Types  (type= option):
      2d          real function(s) of x         \\plot[xmin=-5,xmax=5]{sin(x)}
      parametric  2-D curve x(t),y(t)           \\plot[type=parametric]{cos(t),sin(t)}
      curve3d     3-D curve x(t),y(t),z(t)      \\plot[type=curve3d]{cos(t),sin(t),t/4}
      3d          surface f(x,y)                \\plot[type=3d,xmin=-3,xmax=3,ymin=-3,ymax=3]{sin(x)*cos(y)}
      complex     domain colouring of f(z)      \\plot[type=complex]{z**2-1}
      vector      2-D field u(x,y),v(x,y)       \\plot[type=vector,style=stream]{-y,x}

    Bounds: xmin xmax ymin ymax zmin zmax tmin tmax
    Labels: title xlabel ylabel zlabel
    Size  : figwidth figheight (inches)   width (LaTeX, e.g. 0.8\\linewidth)
    Extra : legend (;-separated)  resolution  density  style=quiver|stream
    """

    _NS: dict = {}

    # Build the eval namespace once and cache it on the class — shared across all instances
    @classmethod
    def _build_ns(cls):
        if cls._NS or not HAS_MPL:
            return
        cls._NS = {
            "__builtins__": {},  # no builtins — keeps eval sandboxed to math functions only
            "pi": np.pi, "e": np.e, "inf": np.inf, "nan": np.nan, "i": 1j,
            "sin": np.sin, "cos": np.cos, "tan": np.tan,
            "sec": lambda x: 1.0/np.cos(x), "csc": lambda x: 1.0/np.sin(x),
            "cot": lambda x: np.cos(x)/np.sin(x),
            "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
            "arcsin": np.arcsin, "arccos": np.arccos,
            "arctan": np.arctan, "arctan2": np.arctan2,
            "exp": np.exp, "log": np.log, "log2": np.log2,
            "log10": np.log10, "ln": np.log,
            "sqrt": np.sqrt, "abs": np.abs, "sign": np.sign,
            "floor": np.floor, "ceil": np.ceil,
            "real": np.real, "imag": np.imag,
            "re": np.real, "im": np.imag,
            "conj": np.conj, "angle": np.angle, "arg": np.angle,
            "norm": np.linalg.norm, "np": np,
        }

    def __init__(self, tex_path: str):
        self._build_ns()
        self.tex_path  = Path(tex_path)
        self.plots_dir = self.tex_path.parent / "_zrkplots"
        self.plots_dir.mkdir(exist_ok=True)
        self.counter   = 0

    def process(self, content: str) -> str:
        spans = self._find_all(content)
        if not spans:
            return content
        out, prev, has_button = [], 0, False
        for start, end, opts_raw, expr_raw in spans:
            out.append(content[prev:start])
            rendered = self._render_one(opts_raw, expr_raw)
            out.append(rendered)
            if "zrkplot://" in rendered:
                has_button = True
            prev = end
        out.append(content[prev:])
        result = "".join(out)
        if has_button and "hyperref" not in result:
            result = re.sub(
                r"(\\documentclass(?:\[.*?\])?\{.*?\})",
                r"\1\n\\usepackage[hidelinks]{hyperref}",
                result, count=1, flags=re.DOTALL,
            )
        return result

    # Scans for every \plot occurrence and returns (start, end, opts_raw, expr_raw) tuples.
    # Uses a brace-depth counter rather than a regex so nested braces/brackets don't trip it up.
    def _find_all(self, src: str):
        results, i = [], 0
        while True:
            pos = src.find(r"\plot", i)
            if pos == -1:
                break
            j = pos + 5
            while j < len(src) and src[j] in " \t":
                j += 1
            opts_raw = ""
            if j < len(src) and src[j] == "[":
                # walk brackets, tracking depth so [a,[b],c] parses correctly
                depth, k = 0, j
                while k < len(src):
                    if src[k] == "[": depth += 1
                    elif src[k] == "]":
                        depth -= 1
                        if depth == 0: break
                    k += 1
                opts_raw = src[j+1:k]; j = k+1
            while j < len(src) and src[j] in " \t\n":
                j += 1
            if j >= len(src) or src[j] != "{":
                i = pos+1; continue
            # same depth trick for the mandatory {expression} argument
            depth, k = 0, j
            while k < len(src):
                if src[k] == "{": depth += 1
                elif src[k] == "}":
                    depth -= 1
                    if depth == 0: break
                k += 1
            results.append((pos, k+1, opts_raw, src[j+1:k]))
            i = k+1
        return results

    # Splits "k1=v1, k2=f(a,b), k3=v3" correctly — the depth counter stops commas
    # inside parentheses (e.g. arctan2(y,x)) from being treated as delimiters.
    def _parse_opts(self, s: str) -> dict:
        opts, depth, cur = {}, 0, []
        for ch in s:
            if ch == "(": depth += 1; cur.append(ch)
            elif ch == ")": depth -= 1; cur.append(ch)
            elif ch == "," and depth == 0:
                self._kv(opts, "".join(cur)); cur = []
            else:
                cur.append(ch)
        self._kv(opts, "".join(cur))
        return opts

    @staticmethod
    def _kv(d, s):
        s = s.strip()
        if "=" in s:
            k, v = s.split("=", 1); d[k.strip()] = v.strip()

    def _fval(self, opts, key, default):
        v = opts.get(key)
        if v is None: return default
        try:
            return float(eval(v, {"pi": np.pi, "e": np.e, "__builtins__": {}}))
        except Exception:
            return default

    def _render_one(self, opts_raw, expr_raw):
        self.counter += 1
        opts  = self._parse_opts(opts_raw)
        ptype = opts.get("type", "2d").lower().replace("-","").replace("_","")
        fw, fh = self._fval(opts,"figwidth",5.5), self._fval(opts,"figheight",4.0)
        out_path  = str(self.plots_dir / f"zrkplot_{self.counter:03d}.pdf")
        hash_path = str(self.plots_dir / f"zrkplot_{self.counter:03d}.hash")
        json_path = str(self.plots_dir / f"zrkplot_{self.counter:03d}.json")

        # Content-hash caching — skip re-rendering if nothing changed
        content_hash = hashlib.md5(f"{opts_raw}|{expr_raw}".encode()).hexdigest()
        cached = (os.path.exists(out_path) and os.path.exists(hash_path) and
                  Path(hash_path).read_text().strip() == content_hash)

        err = None
        if not cached:
            try:
                self._set_style()
                dispatch = {
                    "2d": self._plot_2d, "real": self._plot_2d,
                    "parametric": self._plot_param, "param": self._plot_param,
                    "curve3d": self._plot_curve3d, "parametric3d": self._plot_curve3d,
                    "3d": self._plot_3d, "surface": self._plot_3d,
                    "complex": self._plot_complex,
                    "vector": self._plot_vector, "field": self._plot_vector,
                }
                dispatch.get(ptype, self._plot_2d)(opts, expr_raw, fw, fh)
                plt.tight_layout()
                plt.savefig(out_path, format="pdf", bbox_inches="tight", dpi=150)
                Path(hash_path).write_text(content_hash)
            except Exception as ex:
                err = str(ex)
            finally:
                plt.close("all")

        if err:
            safe = err.replace("\\",r"\textbackslash{}").replace("{",r"\{").replace("}",r"\}")
            return r"\fbox{\texttt{\small Plot error: " + safe + "}}"
        rel = os.path.relpath(out_path, self.tex_path.parent).replace("\\","/")
        width = opts.get("width", r"0.8\linewidth")
        is_btn = bool(re.search(r'\bbutton\b', opts_raw))
        if _PLOTS_MODE or is_btn:
            try:
                with open(json_path, "w") as _f:
                    _json.dump({"type": ptype, "opts_raw": opts_raw,
                                "expr_raw": expr_raw, "fw": fw, "fh": fh,
                                "button": is_btn}, _f)
            except Exception:
                pass
        inc = f"\\includegraphics[width={width}]{{{rel}}}"
        if is_btn:
            return f"\\href{{zrkplot://{self.counter}}}{{{inc}}}"
        return inc

    # The seaborn style name changed in matplotlib 3.6 — try both spellings before giving up
    @staticmethod
    def _set_style():
        for name in ("seaborn-v0_8-whitegrid","seaborn-whitegrid"):
            try: plt.style.use(name); return
            except OSError: pass

    def _ev(self, expr, local_vars):
        return eval(expr, {**self._NS, **local_vars})

    # Like _parse_opts but just splits on top-level commas — used to separate the
    # comma-delimited components of parametric/vector expressions like "cos(t), sin(t)"
    @staticmethod
    def _split_top(s):
        parts, depth, cur = [], 0, []
        for ch in s:
            if ch == "(": depth += 1; cur.append(ch)
            elif ch == ")": depth -= 1; cur.append(ch)
            elif ch == "," and depth == 0: parts.append("".join(cur)); cur = []
            else: cur.append(ch)
        if cur: parts.append("".join(cur))
        return parts

    def _lims(self, ax, opts, axis="both"):
        _e = {"pi": np.pi, "e": np.e, "__builtins__": {}}
        def f(k):
            v = opts.get(k)
            return float(eval(v, _e)) if v else None
        xn,xx,yn,yx = f("xmin"),f("xmax"),f("ymin"),f("ymax")
        if axis in ("x","both") and xn is not None and xx is not None:
            ax.set_xlim(xn, xx)
        if axis in ("y","both") and yn is not None and yx is not None:
            ax.set_ylim(yn, yx)

    def _plot_2d(self, opts, expr, fw, fh):
        xmin = self._fval(opts,"xmin",-5.); xmax = self._fval(opts,"xmax",5.)
        x    = np.linspace(xmin, xmax, 1200)
        exprs   = [e.strip() for e in expr.split(",") if e.strip()]
        legends = [l.strip() for l in opts.get("legend","").split(";") if l.strip()]
        fig, ax = plt.subplots(figsize=(fw,fh))
        for idx, e in enumerate(exprs):
            with np.errstate(all="ignore"):
                y = np.asarray(self._ev(e, {"x": x}), float)
            y = np.where(np.isfinite(y), y, np.nan)
            lbl = legends[idx] if idx < len(legends) else f"${e}$"
            ax.plot(x, y, label=lbl, linewidth=1.8)
        self._lims(ax, opts, "y")
        ax.set_xlabel(opts.get("xlabel","$x$")); ax.set_ylabel(opts.get("ylabel","$y$"))
        if "title" in opts: ax.set_title(opts["title"])
        if len(exprs) > 1 or legends: ax.legend(fontsize=9)
        ax.axhline(0,color="k",lw=0.5,zorder=0); ax.axvline(0,color="k",lw=0.5,zorder=0)

    def _plot_param(self, opts, expr, fw, fh):
        tmin = self._fval(opts,"tmin",0.); tmax = self._fval(opts,"tmax",2*np.pi)
        t = np.linspace(tmin, tmax, 2000)
        parts = [p.strip() for p in self._split_top(expr)]
        if len(parts) < 2: raise ValueError("Parametric needs x(t), y(t)")
        xv = np.asarray(self._ev(parts[0],{"t":t}),float)
        yv = np.asarray(self._ev(parts[1],{"t":t}),float)
        fig, ax = plt.subplots(figsize=(fw,fh))
        ax.plot(xv, yv, linewidth=1.8)
        self._lims(ax, opts, "both")
        ax.set_xlabel(opts.get("xlabel","$x$")); ax.set_ylabel(opts.get("ylabel","$y$"))
        if "title" in opts: ax.set_title(opts["title"])
        ax.set_aspect("equal","datalim")
        ax.axhline(0,color="k",lw=0.5,zorder=0); ax.axvline(0,color="k",lw=0.5,zorder=0)

    def _plot_curve3d(self, opts, expr, fw, fh):
        tmin = self._fval(opts,"tmin",0.); tmax = self._fval(opts,"tmax",2*np.pi)
        t = np.linspace(tmin, tmax, 3000)
        parts = [p.strip() for p in self._split_top(expr)]
        if len(parts) < 3: raise ValueError("3-D curve needs x(t), y(t), z(t)")
        xv = np.asarray(self._ev(parts[0],{"t":t}),float)
        yv = np.asarray(self._ev(parts[1],{"t":t}),float)
        zv = np.asarray(self._ev(parts[2],{"t":t}),float)
        fig = plt.figure(figsize=(fw,fh))
        ax  = fig.add_subplot(111, projection="3d")
        ax.plot(xv, yv, zv, linewidth=1.5)
        ax.set_xlabel(opts.get("xlabel","$x$")); ax.set_ylabel(opts.get("ylabel","$y$"))
        ax.set_zlabel(opts.get("zlabel","$z$"))
        if "title" in opts: ax.set_title(opts["title"])

    def _plot_3d(self, opts, expr, fw, fh):
        xmin=self._fval(opts,"xmin",-5.); xmax=self._fval(opts,"xmax",5.)
        ymin=self._fval(opts,"ymin",-5.); ymax=self._fval(opts,"ymax",5.)
        N = int(self._fval(opts,"resolution",80))
        X,Y = np.meshgrid(np.linspace(xmin,xmax,N), np.linspace(ymin,ymax,N))
        with np.errstate(all="ignore"):
            Z = np.asarray(self._ev(expr.strip(),{"x":X,"y":Y}),float)
        Z = np.where(np.isfinite(Z), Z, np.nan)
        fig = plt.figure(figsize=(fw,fh))
        ax  = fig.add_subplot(111, projection="3d")
        surf = ax.plot_surface(X,Y,Z,cmap="viridis",linewidth=0,antialiased=True,alpha=0.92)
        fig.colorbar(surf, ax=ax, shrink=0.5, pad=0.08)
        ax.set_xlabel(opts.get("xlabel","$x$")); ax.set_ylabel(opts.get("ylabel","$y$"))
        ax.set_zlabel(opts.get("zlabel","$z$"))
        zn,zx = self._fval(opts,"zmin",None), self._fval(opts,"zmax",None)
        if zn is not None and zx is not None: ax.set_zlim(zn, zx)
        if "title" in opts: ax.set_title(opts["title"])

    def _plot_complex(self, opts, expr, fw, fh):
        xmin=self._fval(opts,"xmin",-3.); xmax=self._fval(opts,"xmax",3.)
        ymin=self._fval(opts,"ymin",-3.); ymax=self._fval(opts,"ymax",3.)
        N = int(self._fval(opts,"resolution",500))
        Xg,Yg = np.meshgrid(np.linspace(xmin,xmax,N), np.linspace(ymin,ymax,N))
        Z = Xg + 1j*Yg
        with np.errstate(all="ignore"):
            W = np.asarray(self._ev(expr.strip(),{"z":Z}), complex)
        arg = np.angle(W); mod = np.abs(W)
        # Standard domain colouring: argument -> hue (full circle maps to [0,1])
        hue = (arg + np.pi) / (2*np.pi)
        # Value ramps toward 1 for large |W| but never quite reaches it, so zeros stay dark
        val = 1.0 - 0.5*np.exp(-mod)
        # log2 grid lines: brightness oscillates with each power-of-2 magnitude band,
        # giving the characteristic concentric rings that reveal poles and zeros
        log_m = np.log2(np.where(mod>0, mod, 1e-12))
        val = np.clip(val * (0.5 + 0.15*np.sign(np.cos(2*np.pi*log_m))), 0, 1)
        rgb = mcolors.hsv_to_rgb(np.stack([hue, np.full_like(hue,0.85), val], axis=-1))
        fig, ax = plt.subplots(figsize=(fw,fh))
        ax.imshow(rgb, extent=[xmin,xmax,ymin,ymax], origin="lower",
                  aspect="equal", interpolation="bilinear")
        ax.set_xlabel(opts.get("xlabel",r"$\mathrm{Re}(z)$"))
        ax.set_ylabel(opts.get("ylabel",r"$\mathrm{Im}(z)$"))
        ax.set_title(opts.get("title", f"Domain colouring: $f(z)={expr.strip()}$"))

    def _plot_vector(self, opts, expr, fw, fh):
        xmin=self._fval(opts,"xmin",-5.); xmax=self._fval(opts,"xmax",5.)
        ymin=self._fval(opts,"ymin",-5.); ymax=self._fval(opts,"ymax",5.)
        dens = int(self._fval(opts,"density",20))
        parts = [p.strip() for p in self._split_top(expr)]
        if len(parts) < 2: raise ValueError("Vector field needs u(x,y), v(x,y)")
        style = opts.get("style","quiver").lower()
        fig, ax = plt.subplots(figsize=(fw,fh))
        if style == "stream":
            N = max(dens*10, 200)
            xi = np.linspace(xmin,xmax,N); yi = np.linspace(ymin,ymax,N)
            Xg,Yg = np.meshgrid(xi,yi)
            with np.errstate(all="ignore"):
                U = np.asarray(self._ev(parts[0],{"x":Xg,"y":Yg}),float)
                V = np.asarray(self._ev(parts[1],{"x":Xg,"y":Yg}),float)
            ax.streamplot(xi, yi, U, V, color=np.sqrt(U**2+V**2),
                          cmap="viridis", density=1.5, linewidth=1.2)
        else:
            xi = np.linspace(xmin,xmax,dens); yi = np.linspace(ymin,ymax,dens)
            Xg,Yg = np.meshgrid(xi,yi)
            with np.errstate(all="ignore"):
                U = np.asarray(self._ev(parts[0],{"x":Xg,"y":Yg}),float)
                V = np.asarray(self._ev(parts[1],{"x":Xg,"y":Yg}),float)
            mag  = np.sqrt(U**2+V**2)
            safe = np.where(mag==0, 1., mag)  # avoid divide-by-zero at stagnation points
            # normalise arrows to unit length so the grid looks uniform; colour encodes magnitude
            q = ax.quiver(Xg,Yg,U/safe,V/safe,mag,cmap="viridis",pivot="mid",scale=dens*1.5)
            plt.colorbar(q, ax=ax, label="magnitude")
        ax.set_xlim(xmin,xmax); ax.set_ylim(ymin,ymax)
        ax.set_xlabel(opts.get("xlabel","$x$")); ax.set_ylabel(opts.get("ylabel","$y$"))
        ax.set_aspect("equal")
        if "title" in opts: ax.set_title(opts["title"])
        ax.axhline(0,color="k",lw=0.5,zorder=0); ax.axvline(0,color="k",lw=0.5,zorder=0)


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED COMPILE HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _find_compiler() -> Optional[str]:
    for c in ("pdflatex", "latexmk", "tectonic"):
        if shutil.which(c):
            return c
    return None

def _build_cmd(compiler: str, path: str) -> list:
    return {
        "latexmk":  ["latexmk", "-pdf", "-interaction=nonstopmode", path],
        "tectonic": ["tectonic", path],
    }.get(compiler, ["pdflatex", "-interaction=nonstopmode", path])

def _open_pdf_file(path: str):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])

def _preprocess_plots(path: str) -> Tuple[str, Optional[str], int]:
    """Returns (compile_path, proc_tex_or_None, n_plots)."""
    content = Path(path).read_text(encoding="utf-8")
    if r"\plot" not in content or not HAS_MPL:
        return path, None, 0
    proc = PlotProcessor(path)
    processed = proc.process(content)
    # Ensure graphicx is loaded — the generated \includegraphics lines need it
    if r"\usepackage{graphicx}" not in processed:
        processed = processed.replace(
            r"\begin{document}",
            r"\usepackage{graphicx}" + "\n" + r"\begin{document}", 1)
    # Write to a sibling file so the original .tex stays untouched
    proc_tex = str(Path(path).parent / (Path(path).stem + "_processed.tex"))
    Path(proc_tex).write_text(processed, encoding="utf-8")
    return proc_tex, proc_tex, proc.counter

# After compiling the _processed.tex, copy its PDF back to where the user expects it,
# then delete all the temp files so the workspace stays clean.
def _cleanup_processed(proc_tex: str, original_path: str):
    proc_pdf = str(Path(proc_tex).with_suffix(".pdf"))
    orig_pdf = str(Path(original_path).with_suffix(".pdf"))
    if os.path.exists(proc_pdf):
        shutil.copy2(proc_pdf, orig_pdf)
    for ext in (".tex",".pdf",".aux",".log",".out",".fls",".fdb_latexmk"):
        tmp = str(Path(proc_tex).with_suffix(ext))
        try:
            if os.path.exists(tmp): os.remove(tmp)
        except OSError:
            pass


def _parse_log_errors(log_text: str):
    """Extract (line_number, message) pairs from a pdflatex log.

    pdflatex error format:
      ! LaTeX Error: ...      <- the error message
      ...
      l.42 <context>          <- the line number
    """
    errors = []
    lines = log_text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("!"):
            msg = lines[i][1:].strip()
            # Search the next 20 lines for "l.NNN"
            for j in range(i + 1, min(i + 20, len(lines))):
                m = re.match(r"^l\.(\d+)", lines[j])
                if m:
                    errors.append((int(m.group(1)), msg))
                    break
        i += 1
    return errors


# ══════════════════════════════════════════════════════════════════════════════
#  TUI — vim-like curses editor
# ══════════════════════════════════════════════════════════════════════════════
import platform

try:
    import curses
    import curses.ascii
    HAS_CURSES = True
except ImportError:
    HAS_CURSES = False

class _TuiMode(Enum):
    NORMAL  = "NORMAL"
    INSERT  = "INSERT"
    COMMAND = "COMMAND"
    VISUAL  = "VISUAL"

# curses colour-pair IDs — just numeric constants so we can pass them to color_pair()
C_DEFAULT=1; C_KEYWORD=2; C_COMMENT=3; C_STRING=4; C_NUMBER=5
C_PUNCT=6; C_STATUS=7; C_LINENO=8; C_COMPLETE=9; C_COMP_SEL=10
C_SEARCH=11; C_VISUAL=12

def _init_colors():
    curses.start_color()
    # use_default_colors() lets us use -1 (transparent) for backgrounds, but it's
    # unreliable on Windows — silent failures there cause text to render as black.
    # On Windows we just force COLOR_BLACK so colours are always predictable.
    if sys.platform == "win32":
        BG = curses.COLOR_BLACK
    else:
        try:
            curses.use_default_colors()
            BG = -1
        except Exception:
            BG = curses.COLOR_BLACK
    curses.init_pair(C_DEFAULT,  curses.COLOR_WHITE,   BG)
    curses.init_pair(C_KEYWORD,  curses.COLOR_CYAN,    BG)
    curses.init_pair(C_COMMENT,  curses.COLOR_GREEN,   BG)
    curses.init_pair(C_STRING,   curses.COLOR_YELLOW,  BG)
    curses.init_pair(C_NUMBER,   curses.COLOR_MAGENTA, BG)
    curses.init_pair(C_PUNCT,    curses.COLOR_RED,     BG)
    curses.init_pair(C_STATUS,   curses.COLOR_BLACK,   curses.COLOR_WHITE)
    curses.init_pair(C_LINENO,   curses.COLOR_YELLOW,  BG)
    curses.init_pair(C_COMPLETE, curses.COLOR_BLACK,   curses.COLOR_CYAN)
    curses.init_pair(C_COMP_SEL, curses.COLOR_BLACK,   curses.COLOR_WHITE)
    curses.init_pair(C_SEARCH,   curses.COLOR_BLACK,   curses.COLOR_YELLOW)
    curses.init_pair(C_VISUAL,   curses.COLOR_BLACK,   curses.COLOR_WHITE)

# Maps a pygments token type to a curses colour pair ID.
# Token.Name.Tag catches \commands since pygments treats them as tags in TeX mode.
def _tok_cp(ttype) -> int:
    if not HAS_PYG: return C_DEFAULT
    if ttype in Token.Comment: return C_COMMENT
    if ttype in Token.Keyword or ttype in Token.Name.Builtin or \
       ttype in Token.Name.Function or ttype in Token.Name.Tag: return C_KEYWORD
    if ttype in Token.Literal.String or ttype in Token.String: return C_STRING
    if ttype in Token.Literal.Number or ttype in Token.Number: return C_NUMBER
    if ttype in Token.Operator or ttype in Token.Punctuation: return C_PUNCT
    return C_DEFAULT

# Immutable snapshot of editor state for undo/redo — deepcopy so mutations don't bleed back
class _Snap:
    __slots__ = ("lines","row","col")
    def __init__(self, lines, row, col):
        self.lines = deepcopy(lines); self.row = row; self.col = col

# Caches the tokenised highlight segments so we don't re-lex the whole buffer every frame.
# The cache key is a cheap heuristic (list identity + length + first line) — good enough
# for detecting that nothing changed between redraws without a full hash.
class _HlCache:
    def __init__(self): self._key = None; self._segs = []
    def get(self, lines):
        key = id(lines), len(lines), (lines[0] if lines else "")
        if key == self._key: return self._segs
        self._key  = key
        self._segs = self._tokenize(lines)
        return self._segs
    @staticmethod
    def _tokenize(lines):
        if not HAS_PYG:
            return [[(ln, C_DEFAULT)] for ln in lines]
        text = "\n".join(lines)
        toks = list(_TEX_LEXER.get_tokens(text))
        segs = [[]]
        for ttype, val in toks:
            cp = _tok_cp(ttype)
            for ch in val:
                if ch == "\n":
                    segs.append([])
                else:
                    # Merge consecutive characters with the same colour into a single string
                    # segment — fewer addstr() calls = noticeably faster redraws on large files
                    if segs[-1] and segs[-1][-1][1] == cp:
                        segs[-1][-1] = (segs[-1][-1][0] + ch, cp)
                    else:
                        segs[-1].append((ch, cp))
        while len(segs) < len(lines): segs.append([])
        return segs[:len(lines)]

class Editor:
    MAX_UNDO = 300

    def __init__(self, filename: Optional[str]):
        self.filename  = filename
        self.lines: List[str] = [""]
        self.row = self.col = 0
        self.top = self.left = 0
        self.mode  = _TuiMode.NORMAL
        self.dirty = False
        self.cmd   = ""; self.msg = ""
        self.undo_stack: List[_Snap] = []
        self.redo_stack: List[_Snap] = []
        self.vis_row = self.vis_col = 0
        self.search_pat = ""; self.matches: List[Tuple[int,int]] = []; self.match_idx = 0
        self.ac_list: List[str] = []; self.ac_idx = -1; self.ac_prefix = ""
        self._pend = ""; self._cnt = ""
        self.reg = ""; self.reg_lines = False
        self._hl = _HlCache()
        if filename and os.path.exists(filename): self._load()
        elif filename: self._new_template()

    # ── I/O ──────────────────────────────────────────────────────────────────
    def _load(self):
        try:
            text = Path(self.filename).read_text(encoding="utf-8")
            self.lines = text.splitlines() or [""]
            self.dirty = False
            self.msg   = f'"{self.filename}" loaded ({len(self.lines)} lines)'
        except Exception as ex:
            self.msg = f"Error loading: {ex}"

    def _new_template(self):
        self.lines = [
            r"\documentclass[12pt]{article}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage{amsmath, amssymb}",
            r"\usepackage{graphicx}",
            r"",
            r"\begin{document}",
            r"",
            r"",
            r"\end{document}",
        ]
        self.dirty = True; self.row = 7; self.col = 0
        self.msg = f'New file "{self.filename}"'

    def _save(self) -> bool:
        if not self.filename:
            self.msg = "No filename — use :w <name>"; return False
        try:
            Path(self.filename).write_text("\n".join(self.lines)+"\n", encoding="utf-8")
            self.dirty = False
            self.msg   = f'"{self.filename}" written ({len(self.lines)} lines)'
            return True
        except Exception as ex:
            self.msg = f"Write error: {ex}"; return False

    def _compile(self) -> bool:
        if not self.filename:
            self.msg = "No filename to compile."; return False
        compiler = _find_compiler()
        if not compiler:
            self.msg = "No LaTeX compiler found (install pdflatex/MiKTeX/TeX Live)."; return False
        wd = str(Path(self.filename).parent.resolve())

        # Plot preprocessing
        compile_path, proc_tex, n_plots = _preprocess_plots(self.filename)
        if n_plots:
            self.msg = f"Preprocessed {n_plots} plot(s)…"

        cmd = _build_cmd(compiler, os.path.abspath(compile_path))
        self.msg = f"Compiling with {compiler}…"
        try:
            r = subprocess.run(cmd, cwd=wd, capture_output=True, text=True, timeout=120)
            if proc_tex:
                _cleanup_processed(proc_tex, self.filename)
            if r.returncode == 0:
                self.msg = "Compiled OK!"; return True
            out = r.stdout or r.stderr or ""
            parsed = _parse_log_errors(out)
            if parsed:
                line_no, msg = parsed[0]
                self.msg = f"Error at l.{line_no}: {msg[:70]}"
                # Jump cursor to error line (clamp to file length)
                self.row = max(0, min(line_no - 1, len(self.lines) - 1)); self.col = 0
            else:
                raw = [ln for ln in out.splitlines() if ln.startswith("!")]
                self.msg = ("Error: " + raw[0][:80]) if raw else "Compile failed (check .log)."
            return False
        except subprocess.TimeoutExpired:
            self.msg = "Compile timed out."; return False
        except Exception as ex:
            self.msg = f"Compile error: {ex}"; return False

    def _open_pdf(self):
        if not self.filename: return
        pdf = str(Path(self.filename).with_suffix(".pdf"))
        if os.path.exists(pdf):
            _open_pdf_file(pdf)

    # ── Undo/Redo ─────────────────────────────────────────────────────────────
    def _push(self):
        self.undo_stack.append(_Snap(self.lines, self.row, self.col))
        if len(self.undo_stack) > self.MAX_UNDO: self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _undo(self):
        if not self.undo_stack: self.msg = "Already at oldest change."; return
        self.redo_stack.append(_Snap(self.lines, self.row, self.col))
        s = self.undo_stack.pop()
        self.lines, self.row, self.col = s.lines, s.row, s.col
        self.dirty = True; self._clamp()

    def _redo(self):
        if not self.redo_stack: self.msg = "Already at newest change."; return
        self.undo_stack.append(_Snap(self.lines, self.row, self.col))
        s = self.redo_stack.pop()
        self.lines, self.row, self.col = s.lines, s.row, s.col
        self.dirty = True; self._clamp()

    # ── Cursor ────────────────────────────────────────────────────────────────
    def _clamp(self):
        self.row = max(0, min(self.row, len(self.lines)-1))
        llen = len(self.lines[self.row])
        # In normal mode the cursor can't sit past the last character (vim behaviour);
        # in insert mode it can sit one position beyond to allow appending at EOL
        maxc = max(0, llen-(1 if self.mode==_TuiMode.NORMAL and llen>0 else 0))
        self.col = max(0, min(self.col, maxc))

    # Adjusts the viewport (top/left) to keep the cursor on screen.
    # h-2 leaves room for the status bar and command line at the bottom.
    def _scroll(self, h, w, lw):
        cw = w - lw
        if self.row < self.top: self.top = self.row
        elif self.row >= self.top+h-2: self.top = self.row-h+3
        if self.col < self.left: self.left = self.col
        elif self.col >= self.left+cw-1: self.left = self.col-cw+2
        self.top = max(0,self.top); self.left = max(0,self.left)

    # ── Search ────────────────────────────────────────────────────────────────
    def _search(self, pat):
        self.search_pat = pat; self.matches = []
        if not pat: return
        try: rx = re.compile(pat)
        except re.error: rx = re.compile(re.escape(pat))
        for r, line in enumerate(self.lines):
            for m in rx.finditer(line):
                self.matches.append((r, m.start()))

    def _next_match(self, fwd=True):
        if not self.matches: self.msg = f"/{self.search_pat}: Not found"; return
        if fwd:
            for i,(r,c) in enumerate(self.matches):
                if (r,c) > (self.row,self.col): self.match_idx=i; self.row,self.col=r,c; return
            self.match_idx = 0
        else:
            for i in range(len(self.matches)-1,-1,-1):
                r,c = self.matches[i]
                if (r,c) < (self.row,self.col): self.match_idx=i; self.row,self.col=r,c; return
            self.match_idx = len(self.matches)-1
        self.row, self.col = self.matches[self.match_idx]

    # ── Autocomplete ──────────────────────────────────────────────────────────
    # Walk left from the cursor to find the start of a \command being typed.
    # Returns the partial command (backslash included) or "" if the cursor isn't in one.
    def _ac_prefix(self):
        line = self.lines[self.row]; i = self.col-1
        while i >= 0 and (line[i].isalpha() or line[i] in "*@"): i -= 1
        if i >= 0 and line[i] == "\\": return line[i:self.col]
        return ""

    def _ac_update(self):
        line = self.lines[self.row][:self.col]
        # \plot option/value completion takes priority
        ctx = _plot_option_context(line)
        if ctx is not None:
            prefix, candidates = ctx
            self.ac_prefix = prefix
            self.ac_list   = candidates[:12]
            self.ac_idx    = 0 if self.ac_list else -1
            return
        # Regular \command completion
        prefix = self._ac_prefix()
        if not prefix or prefix == "\\":
            self.ac_list=[]; self.ac_idx=-1; self.ac_prefix=""; return
        self.ac_prefix = prefix
        self.ac_list   = [c for c in LATEX_COMMANDS if c.startswith(prefix)][:12]
        if not self.ac_list: self.ac_idx = -1
        elif self.ac_idx >= len(self.ac_list): self.ac_idx = 0

    def _ac_apply(self):
        if self.ac_idx < 0 or not self.ac_list: return
        comp = self.ac_list[self.ac_idx]; prefix = self.ac_prefix
        line = self.lines[self.row]; start = self.col-len(prefix)
        self.lines[self.row] = line[:start]+comp+line[self.col:]
        self.col = start+len(comp); self.ac_list=[]; self.ac_idx=-1; self.dirty=True

    # ── Word movement ─────────────────────────────────────────────────────────
    def _word_fwd(self):
        line=self.lines[self.row]; col=self.col
        while col<len(line) and not line[col].isspace(): col+=1
        while col<len(line) and line[col].isspace(): col+=1
        if col>=len(line) and self.row<len(self.lines)-1: self.row+=1; self.col=0
        else: self.col=col

    def _word_bwd(self):
        col=self.col
        if col==0:
            if self.row>0: self.row-=1; self.col=len(self.lines[self.row])
            return
        line=self.lines[self.row]; col-=1
        while col>0 and line[col].isspace(): col-=1
        while col>0 and not line[col-1].isspace(): col-=1
        self.col=col

    def _word_end(self):
        line=self.lines[self.row]; col=self.col+1
        if col>=len(line):
            if self.row<len(self.lines)-1: self.row+=1; self.col=0
            return
        while col<len(line)-1 and line[col].isspace(): col+=1
        while col<len(line)-1 and not line[col+1].isspace(): col+=1
        self.col=col

    # ── Drawing ───────────────────────────────────────────────────────────────
    def _draw(self, scr):
        scr.erase(); h,w = scr.getmaxyx()
        # Line-number gutter width grows with the file — always wide enough for the last line number
        lw = len(str(len(self.lines)))+2
        self._scroll(h,w,lw)
        ch_h = h-2; cw = w-lw
        segs_all = self._hl.get(self.lines)
        hit_set  = set(self.matches)  # set for O(1) lookup per character cell
        if self.mode == _TuiMode.VISUAL:
            vr1=min(self.vis_row,self.row); vr2=max(self.vis_row,self.row)
        else:
            vr1=vr2=-1
        for sr in range(ch_h):
            br = self.top+sr
            if br >= len(self.lines):
                try: scr.addstr(sr,0,"~",curses.color_pair(C_LINENO))  # vim-style tilde for empty rows
                except curses.error: pass
                continue
            lno = f"{br+1:>{lw-1}} "
            try: scr.addstr(sr,0,lno,curses.color_pair(C_LINENO))
            except curses.error: pass
            line = self.lines[br]
            segs = segs_all[br] if br<len(segs_all) else [(line,C_DEFAULT)]
            x=lw; char_x=self.left
            for text,cp in segs:
                for c in text:
                    if char_x<self.left: char_x+=1; continue
                    if x>=w-1: break
                    attr = curses.color_pair(cp)
                    # Visual selection overrides syntax colour; search highlight overrides that
                    if vr1<=br<=vr2: attr=curses.color_pair(C_VISUAL)|curses.A_REVERSE
                    if (br,char_x) in hit_set: attr=curses.color_pair(C_SEARCH)|curses.A_BOLD
                    try: scr.addstr(sr,x,c,attr)
                    except curses.error: pass
                    x+=1; char_x+=1
        mstr=f" {self.mode.value} "; fn=self.filename or "[No Name]"
        fstr=f" {fn}{'*' if self.dirty else ''} "; pstr=f" {self.row+1}:{self.col+1} "
        # Pad the middle section so the position counter stays right-aligned
        bar=(mstr+fstr+" "*max(0,w-len(mstr)-len(fstr)-len(pstr))+pstr)[:w]
        try: scr.addstr(h-2,0,bar,curses.color_pair(C_STATUS)|curses.A_BOLD)
        except curses.error: pass
        if self.mode==_TuiMode.COMMAND:
            cl=(":"+self.cmd)[:w]
            try: scr.addstr(h-1,0,cl); scr.move(h-1,min(len(cl),w-1))
            except curses.error: pass
        elif self.msg:
            try: scr.addstr(h-1,0,self.msg[:w])
            except curses.error: pass
        if self.ac_list and self.mode==_TuiMode.INSERT:
            self._draw_ac(scr,h,w,lw)
        if self.mode!=_TuiMode.COMMAND:
            sr=self.row-self.top; sc=lw+self.col-self.left
            if 0<=sr<h-2 and 0<=sc<w:
                try: scr.move(sr,sc)
                except curses.error: pass
        scr.refresh()

    def _draw_ac(self, scr, h, w, lw):
        sr=self.row-self.top; sc=lw+self.col-self.left-len(self.ac_prefix)
        n=min(len(self.ac_list),10)
        pw=max((len(c) for c in self.ac_list[:n]),default=10)+2
        pr=sr+1 if sr+1+n<h-2 else sr-n; pc=max(0,min(sc,w-pw-1))
        for i,item in enumerate(self.ac_list[:n]):
            text=f" {item:<{pw-1}}"[:pw]
            cp=C_COMP_SEL if i==self.ac_idx else C_COMPLETE
            try: scr.addstr(pr+i,pc,text,curses.color_pair(cp))
            except curses.error: pass

    # ── Normal mode ───────────────────────────────────────────────────────────
    def _normal(self, key) -> bool:
        ch = chr(key) if 0<key<256 else ""
        # Accumulate count prefix (e.g. "10j" moves 10 lines down); "0" alone is go-to-col-0
        if ch.isdigit() and (ch!="0" or self._cnt): self._cnt+=ch; return True
        n=int(self._cnt) if self._cnt else 1; self._cnt=""
        # Handle two-stroke sequences like "gg", "dd", "yy"
        if self._pend:
            p,self._pend = self._pend,""
            if p=="g":
                if ch=="g": self.row=0; self.col=0
            elif p=="d":
                if ch=="d":
                    self._push()
                    for _ in range(n):
                        if len(self.lines)>1: del self.lines[self.row]; self.row=min(self.row,len(self.lines)-1)
                        else: self.lines[0]=""
                    self.dirty=True; self._clamp()
            elif p=="y":
                if ch=="y":
                    self.reg="\n".join(self.lines[self.row:self.row+n]); self.reg_lines=True
                    self.msg=f"Yanked {n} line(s)"
            return True
        if   key==curses.KEY_UP   or ch=="k": self.row=max(0,self.row-n); self._clamp()
        elif key==curses.KEY_DOWN  or ch=="j": self.row=min(len(self.lines)-1,self.row+n); self._clamp()
        elif key==curses.KEY_LEFT  or ch=="h": self.col=max(0,self.col-n)
        elif key==curses.KEY_RIGHT or ch=="l": self.col=min(max(0,len(self.lines[self.row])-1),self.col+n)
        elif key==curses.KEY_HOME  or ch=="0": self.col=0
        elif key==curses.KEY_END   or ch=="$": self.col=max(0,len(self.lines[self.row])-1)
        elif ch=="^": ln=self.lines[self.row]; self.col=len(ln)-len(ln.lstrip())
        elif ch=="w": [self._word_fwd() for _ in range(n)]
        elif ch=="b": [self._word_bwd() for _ in range(n)]
        elif ch=="e": [self._word_end() for _ in range(n)]
        elif ch=="G": self.row=len(self.lines)-1; self.col=0
        elif ch=="g": self._pend="g"
        elif key==curses.KEY_PPAGE or key==339: self.row=max(0,self.row-20); self._clamp()
        elif key==curses.KEY_NPAGE or key==338: self.row=min(len(self.lines)-1,self.row+20); self._clamp()
        elif key==4:  self.row=min(len(self.lines)-1,self.row+10); self._clamp()  # Ctrl-D
        elif key==21: self.row=max(0,self.row-10); self._clamp()                  # Ctrl-U
        elif ch=="i": self._push(); self.mode=_TuiMode.INSERT
        elif ch=="I":
            self._push(); self.mode=_TuiMode.INSERT
            self.col=len(self.lines[self.row])-len(self.lines[self.row].lstrip())
        elif ch=="a":
            self._push(); self.mode=_TuiMode.INSERT
            if self.lines[self.row]: self.col=min(self.col+1,len(self.lines[self.row]))
        elif ch=="A":
            self._push(); self.mode=_TuiMode.INSERT; self.col=len(self.lines[self.row])
        elif ch=="o":
            self._push(); self.row+=1
            indent=len(self.lines[self.row-1])-len(self.lines[self.row-1].lstrip())
            self.lines.insert(self.row," "*indent); self.col=indent; self.mode=_TuiMode.INSERT; self.dirty=True
        elif ch=="O":
            self._push()
            indent=len(self.lines[self.row])-len(self.lines[self.row].lstrip())
            self.lines.insert(self.row," "*indent); self.col=indent; self.mode=_TuiMode.INSERT; self.dirty=True
        elif ch=="x":
            self._push(); line=self.lines[self.row]
            if self.col<len(line): self.lines[self.row]=line[:self.col]+line[self.col+1:]; self.dirty=True; self._clamp()
        elif ch=="D":
            self._push(); self.lines[self.row]=self.lines[self.row][:self.col]; self.dirty=True
        elif ch=="d": self._pend="d"
        elif ch=="J":
            self._push()
            if self.row<len(self.lines)-1:
                self.lines[self.row]=self.lines[self.row].rstrip()+" "+self.lines[self.row+1].lstrip()
                del self.lines[self.row+1]; self.dirty=True
        elif ch=="y": self._pend="y"
        elif ch=="Y": self.reg=self.lines[self.row]; self.reg_lines=True; self.msg="Yanked line"
        elif ch=="p":
            self._push()
            if self.reg_lines: self.lines.insert(self.row+1,self.reg); self.row+=1
            else:
                ln=self.lines[self.row]; self.lines[self.row]=ln[:self.col+1]+self.reg+ln[self.col+1:]
                self.col+=len(self.reg)
            self.dirty=True
        elif ch=="P":
            self._push()
            if self.reg_lines: self.lines.insert(self.row,self.reg)
            else:
                ln=self.lines[self.row]; self.lines[self.row]=ln[:self.col]+self.reg+ln[self.col:]
            self.dirty=True
        elif ch=="u": self._undo()
        elif key==18: self._redo()  # Ctrl-R
        elif ch=="/": self.mode=_TuiMode.COMMAND; self.cmd="/"
        elif ch=="n": self._next_match(True)
        elif ch=="N": self._next_match(False)
        elif ch==":": self.mode=_TuiMode.COMMAND; self.cmd=""
        elif ch=="v": self.mode=_TuiMode.VISUAL; self.vis_row=self.row; self.vis_col=self.col
        return True

    # ── Insert mode ───────────────────────────────────────────────────────────
    def _insert(self, key) -> bool:
        ch = chr(key) if 0<key<256 else ""
        if key==27:
            self.mode=_TuiMode.NORMAL; self.col=max(0,self.col-1)
            self.ac_list=[]; self.ac_idx=-1; return True
        if self.ac_list:
            if key==9 or key==curses.KEY_DOWN: self.ac_idx=(self.ac_idx+1)%len(self.ac_list); return True
            if key==curses.KEY_UP: self.ac_idx=(self.ac_idx-1)%len(self.ac_list); return True
            if key in (10,13) and self.ac_idx>=0: self._ac_apply(); return True
        if key==9:
            prefix=self._ac_prefix()
            if prefix: self._ac_update(); self.ac_idx=0 if self.ac_list else -1
            else:
                line=self.lines[self.row]; self.lines[self.row]=line[:self.col]+"    "+line[self.col:]
                self.col+=4; self.dirty=True
            return True
        if key in (8,127,curses.KEY_BACKSPACE):
            line=self.lines[self.row]
            if self.col>0:
                # If the cursor is between a matching pair (e.g. "{}"), delete both at once
                if self.col<len(line) and line[self.col-1]+line[self.col] in ("{}","[]","()","$$"):
                    self.lines[self.row]=line[:self.col-1]+line[self.col+1:]
                else:
                    self.lines[self.row]=line[:self.col-1]+line[self.col:]
                self.col-=1
            elif self.row>0:
                prev=self.lines[self.row-1]; self.col=len(prev)
                self.lines[self.row-1]=prev+line; del self.lines[self.row]; self.row-=1
            self.dirty=True; self._ac_update(); return True
        if key==curses.KEY_DC:
            line=self.lines[self.row]
            if self.col<len(line): self.lines[self.row]=line[:self.col]+line[self.col+1:]
            elif self.row<len(self.lines)-1:
                self.lines[self.row]=line+self.lines[self.row+1]; del self.lines[self.row+1]
            self.dirty=True; return True
        if key in (10,13):
            line=self.lines[self.row]; before=line[:self.col]; after=line[self.col:]
            indent=len(before)-len(before.lstrip()); stripped=before.rstrip()
            # Extra indent after "{" or \begin{...} — mirrors the GUI's auto-indent logic
            if stripped.endswith("{") or re.search(r'\\begin\{[^}]*\}$',stripped): indent+=4
            self.lines[self.row]=before; self.row+=1
            self.lines.insert(self.row," "*indent+after); self.col=indent; self.dirty=True
            self.ac_list=[]; return True
        if key==curses.KEY_UP:    self.row=max(0,self.row-1); self._clamp(); return True
        if key==curses.KEY_DOWN:  self.row=min(len(self.lines)-1,self.row+1); self._clamp(); return True
        if key==curses.KEY_LEFT:  self.col=max(0,self.col-1); return True
        if key==curses.KEY_RIGHT: self.col=min(len(self.lines[self.row]),self.col+1); return True
        if key==curses.KEY_HOME:  self.col=0; return True
        if key==curses.KEY_END:   self.col=len(self.lines[self.row]); return True
        if 32<=key<256:
            line=self.lines[self.row]; self.lines[self.row]=line[:self.col]+ch+line[self.col:]
            self.col+=1; self.dirty=True
            # Auto-close brackets/braces/dollar signs — cursor lands between them
            pairs={"{":"}","[":"]","(":")",  "$":"$"}
            if ch in pairs:
                ln=self.lines[self.row]; self.lines[self.row]=ln[:self.col]+pairs[ch]+ln[self.col:]
            self._ac_update()
        return True

    # ── Command mode ──────────────────────────────────────────────────────────
    def _command(self, key) -> bool:
        if key==27: self.mode=_TuiMode.NORMAL; self.cmd=""; return True
        if key in (10,13): return self._exec()
        if key in (8,127,curses.KEY_BACKSPACE):
            if self.cmd:
                self.cmd=self.cmd[:-1]
                if self.cmd.startswith("/") and len(self.cmd)>1: self._search(self.cmd[1:])
            else:
                self.mode=_TuiMode.NORMAL
            return True
        if 32<=key<256:
            self.cmd+=chr(key)
            # Incremental search — highlight matches as the pattern grows
            if self.cmd.startswith("/") and len(self.cmd)>1: self._search(self.cmd[1:])
            return True
        return True

    def _exec(self) -> bool:
        raw=self.cmd; self.cmd=""; self.mode=_TuiMode.NORMAL
        if raw.startswith("/"):
            self._search(raw[1:]); self._next_match(True); return True
        parts=raw.strip().split(None,1); c0=parts[0] if parts else ""
        if c0=="q":
            if self.dirty: self.msg="Unsaved changes — use :wq or :q!"; return True
            return False
        elif c0=="q!": return False
        elif c0=="w":
            if len(parts)>1: self.filename=parts[1].strip()
            self._save()
        elif c0 in ("wq","x"):
            if len(parts)>1: self.filename=parts[1].strip()
            if self._save():
                if self._compile(): self._open_pdf(); return False
        elif c0=="pdf": self._save(); self._compile()
        elif c0=="e":
            if len(parts)>1:
                self.filename=parts[1].strip(); self._load()
                self.row=self.col=self.top=self.left=0
            else: self.msg="Usage: :e <filename>"
        else: self.msg=f"Unknown command: {c0}"
        return True

    # ── Visual mode ───────────────────────────────────────────────────────────
    def _visual(self, key) -> bool:
        ch=chr(key) if 0<key<256 else ""
        if key==27 or ch=="v": self.mode=_TuiMode.NORMAL; return True
        if key==curses.KEY_UP   or ch=="k": self.row=max(0,self.row-1)
        elif key==curses.KEY_DOWN or ch=="j": self.row=min(len(self.lines)-1,self.row+1)
        elif key==curses.KEY_LEFT  or ch=="h": self.col=max(0,self.col-1)
        elif key==curses.KEY_RIGHT or ch=="l": self.col=min(max(0,len(self.lines[self.row])-1),self.col+1)
        elif ch=="0": self.col=0
        elif ch=="$": self.col=max(0,len(self.lines[self.row])-1)
        elif ch=="G": self.row=len(self.lines)-1
        elif ch=="w": self._word_fwd()
        elif ch=="b": self._word_bwd()
        elif ch in ("d","x"):
            self._push()
            r1=min(self.vis_row,self.row); r2=max(self.vis_row,self.row)
            self.reg="\n".join(self.lines[r1:r2+1]); self.reg_lines=True
            del self.lines[r1:r2+1]
            if not self.lines: self.lines=[""]
            self.row=r1; self._clamp(); self.dirty=True; self.mode=_TuiMode.NORMAL
        elif ch=="y":
            r1=min(self.vis_row,self.row); r2=max(self.vis_row,self.row)
            self.reg="\n".join(self.lines[r1:r2+1]); self.reg_lines=True
            self.msg=f"Yanked {r2-r1+1} line(s)"; self.mode=_TuiMode.NORMAL
        return True

    # ── Main loop ─────────────────────────────────────────────────────────────
    def _main(self, scr):
        _init_colors(); curses.curs_set(1); scr.keypad(True)
        while True:
            self._draw(scr)
            try: key=scr.get_wch()
            except curses.error: continue
            if isinstance(key,str): key=ord(key)
            self.msg=""
            if   self.mode==_TuiMode.NORMAL:  cont=self._normal(key)
            elif self.mode==_TuiMode.INSERT:  cont=self._insert(key)
            elif self.mode==_TuiMode.COMMAND: cont=self._command(key)
            elif self.mode==_TuiMode.VISUAL:  cont=self._visual(key)
            else: cont=True
            if not cont: break

    def run(self):
        curses.wrapper(self._main)


# ══════════════════════════════════════════════════════════════════════════════
#  GUI — tkinter editor with PDF preview
# ══════════════════════════════════════════════════════════════════════════════
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

T = {
    "bg":"#1e1e1e","fg":"#d4d4d4","ln_bg":"#252526","ln_fg":"#858585",
    "sel":"#264f78","cmd":"#4ec9b0","cmt":"#6a9955","brc":"#ffd700",
    "num":"#b5cea8","mth":"#ce9178","err_bg":"#5a1d1d",
    "tbar":"#2d2d2d","stat":"#007acc","stat_fg":"#ffffff",
    "ac_bg":"#252526","ac_sel":"#094771","ac_fg":"#d4d4d4",
    "sash":"#3c3c3c","out_bg":"#1e1e1e","ok":"#4ec9b0","err":"#f48771",
}
FONT    = ("Consolas",12)
FONT_SM = ("Consolas",10)
FONT_UI = ("Segoe UI",9)


class LineNumbers(tk.Canvas):
    WIDTH = 52
    def __init__(self, master, text, **kw):
        kw.setdefault("bg",T["ln_bg"]); kw.setdefault("bd",0)
        kw.setdefault("highlightthickness",0); kw.setdefault("width",self.WIDTH)
        super().__init__(master,**kw)
        self._text=text
        for ev in ("<<Modified>>","<Configure>","<KeyRelease>","<ButtonRelease>"):
            self._text.bind(ev,self._redraw,add=True)

    def _redraw(self,*_):
        self.delete("all")
        self.create_line(self.WIDTH-1,0,self.WIDTH-1,self.winfo_height(),fill="#3c3c3c")
        idx=self._text.index("@0,0")
        while True:
            dline=self._text.dlineinfo(idx)
            if dline is None: break
            y=dline[1]; lineno=int(str(idx).split(".")[0])
            self.create_text(self.WIDTH-8,y,anchor="ne",text=str(lineno),fill=T["ln_fg"],font=FONT_SM)
            nxt=self._text.index(f"{idx}+1line")
            if nxt==idx: break
            idx=nxt


class AutoComplete:
    MAX=10
    def __init__(self, editor, root):
        self._ed=editor; self._root=root
        self._win=None; self._lb=None
        self._items=[]; self._prefix=""

    def update(self):
        line = self._ed.get("insert linestart", "insert")
        # \plot option/value completion takes priority
        ctx = _plot_option_context(line)
        if ctx is not None:
            prefix, candidates = ctx
            if candidates:
                self._show(candidates, prefix)
            else:
                self.hide()
            return
        # Regular \command completion
        m = re.search(r"\\[a-zA-Z]*$", line)
        if not m:
            self.hide(); return
        prefix = m.group(0)
        matches = [c for c in LATEX_COMMANDS if c.startswith(prefix)]
        if matches: self._show(matches, prefix)
        else: self.hide()

    def visible(self): return self._win is not None

    def move(self,delta):
        if not self._lb: return
        sel=self._lb.curselection(); idx=(sel[0] if sel else 0)+delta
        idx=max(0,min(idx,len(self._items)-1))
        self._lb.selection_clear(0,tk.END); self._lb.selection_set(idx); self._lb.see(idx)

    def apply(self):
        if not self._lb: return False
        sel=self._lb.curselection()
        if not sel: return False
        chosen=self._items[sel[0]]
        ins=self._ed.index(tk.INSERT)
        self._ed.delete(f"{ins} -{len(self._prefix)}c",ins)
        self._ed.insert(tk.INSERT,chosen); self.hide(); return True

    def hide(self):
        if self._win: self._win.destroy(); self._win=None; self._lb=None
        self._items=[]; self._prefix=""

    def _show(self,items,prefix):
        self._items=items[:self.MAX]; self._prefix=prefix
        if self._win is None:
            self._win=tk.Toplevel(self._root); self._win.overrideredirect(True)
            self._win.attributes("-topmost",True)
            self._lb=tk.Listbox(self._win,bg=T["ac_bg"],fg=T["ac_fg"],
                selectbackground=T["ac_sel"],selectforeground=T["ac_fg"],
                font=FONT_SM,bd=0,highlightthickness=1,
                highlightbackground="#007acc",activestyle="none")
            self._lb.pack(fill=tk.BOTH,expand=True)
            self._lb.bind("<ButtonRelease-1>",lambda _:self.apply())
        self._lb.delete(0,tk.END)
        for it in self._items: self._lb.insert(tk.END,it)
        self._lb.selection_set(0); self._place()

    def _place(self):
        try: bbox=self._ed.bbox(tk.INSERT)
        except Exception: return
        if bbox is None: return
        x=self._ed.winfo_rootx()+bbox[0]; y=self._ed.winfo_rooty()+bbox[1]+bbox[3]+2
        self._win.geometry(f"230x{len(self._items)*19+4}+{x}+{y}")



class PDFViewer(tk.Frame):
    def __init__(self,master,on_plot_open=None,**kw):
        kw.setdefault("bg",T["tbar"]); super().__init__(master,**kw)
        self._zoom=1.0; self._path=None; self._imgs=[]
        self._on_plot_open = on_plot_open
        self._plot_rects: list = []  # (x1,y1,x2,y2,json_path) in canvas pixels, from link annotations

        hdr=tk.Frame(self,bg=T["tbar"],height=28); hdr.pack(fill=tk.X,side=tk.TOP); hdr.pack_propagate(False)
        tk.Label(hdr,text="PDF Preview",bg=T["tbar"],fg=T["ln_fg"],font=FONT_UI).pack(side=tk.LEFT,padx=8)
        # Plots button — hidden until --plots mode is active and plots are ready
        self._plots_btn=tk.Button(hdr,text="Plots ▾",command=self._show_plots_menu,
                                  bg=T["tbar"],fg=T["cmd"],relief=tk.FLAT,
                                  font=FONT_UI,padx=6,pady=0)
        # packed lazily by set_plots_dir when plots are available
        tk.Button(hdr,text="+",command=self._zoom_in,bg=T["tbar"],fg=T["fg"],relief=tk.FLAT,
                  font=("Consolas",11),padx=4,pady=0).pack(side=tk.RIGHT,padx=2,pady=3)
        self._zlbl=tk.Label(hdr,text="100%",bg=T["tbar"],fg=T["fg"],font=FONT_UI,width=5)
        self._zlbl.pack(side=tk.RIGHT)
        tk.Button(hdr,text="−",command=self._zoom_out,bg=T["tbar"],fg=T["fg"],relief=tk.FLAT,
                  font=("Consolas",11),padx=4,pady=0).pack(side=tk.RIGHT,padx=2,pady=3)
        inner=tk.Frame(self,bg=T["bg"]); inner.pack(fill=tk.BOTH,expand=True)
        self._canvas=tk.Canvas(inner,bg="#3a3a3a",bd=0,highlightthickness=0)
        vsb=ttk.Scrollbar(inner,orient=tk.VERTICAL,command=self._canvas.yview)
        hsb=ttk.Scrollbar(self,orient=tk.HORIZONTAL,command=self._canvas.xview)
        self._canvas.configure(yscrollcommand=vsb.set,xscrollcommand=hsb.set)
        hsb.pack(side=tk.BOTTOM,fill=tk.X); vsb.pack(side=tk.RIGHT,fill=tk.Y)
        self._canvas.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
        self._canvas.bind("<MouseWheel>",lambda e:self._canvas.yview_scroll(-1*(e.delta//120),"units"))
        self._canvas.bind("<Button-1>", self._on_canvas_click)
        self._canvas.bind("<Button-3>", self._on_canvas_click)
        self._canvas.bind("<Motion>",   self._on_canvas_motion)
        self._placeholder()

    def set_plots_dir(self, plots_dir: Optional[str], on_plot_open=None):
        """Called by App after a compile for the --plots Plots ▾ button."""
        if on_plot_open:
            self._on_plot_open = on_plot_open
        has_plots = (_PLOTS_MODE and bool(plots_dir and os.path.isdir(plots_dir) and
                         any(f.endswith(".json") for f in os.listdir(plots_dir))))
        if has_plots:
            self._plots_btn.pack(side=tk.LEFT, padx=4, pady=3)
        else:
            self._plots_btn.pack_forget()

    def _plots_dir(self):
        """Derive the _zrkplots directory from the currently loaded PDF path."""
        if not self._path:
            return None
        d = str(Path(self._path).parent / "_zrkplots")
        return d if os.path.isdir(d) else None

    def _json_files(self):
        d = self._plots_dir()
        if not d:
            return []
        return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json"))

    def _show_plots_menu(self, event=None):
        jsons = self._json_files()
        if not jsons:
            menu = tk.Menu(self, tearoff=False, bg=T["tbar"], fg=T["ln_fg"], bd=0)
            menu.add_command(label="No plots yet — compile a document with \\plot",
                             state=tk.DISABLED)
            try:
                x = self._plots_btn.winfo_rootx()
                y = self._plots_btn.winfo_rooty() + self._plots_btn.winfo_height()
                menu.tk_popup(x, y)
            finally:
                menu.grab_release()
            return
        menu = tk.Menu(self, tearoff=False, bg=T["tbar"], fg=T["fg"],
                       activebackground=T["sel"], activeforeground=T["fg"], bd=0)
        for jpath in jsons:
            try:
                d = _json.loads(Path(jpath).read_text())
                label = f"{d['type']:10s}  {d['expr_raw'][:45]}"
            except Exception:
                label = os.path.basename(jpath)
            menu.add_command(label=label,
                             command=lambda p=jpath: self._open_plot(p))
        try:
            x = self._plots_btn.winfo_rootx()
            y = self._plots_btn.winfo_rooty() + self._plots_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _hit(self, event):
        """Return the json_path of the button-plot rect under the cursor, or None."""
        cx=self._canvas.canvasx(event.x); cy=self._canvas.canvasy(event.y)
        for x1,y1,x2,y2,jp in self._plot_rects:
            if x1<=cx<=x2 and y1<=cy<=y2:
                return jp
        return None

    def _on_canvas_motion(self, event):
        self._canvas.config(cursor="hand2" if self._hit(event) else "")

    def _on_canvas_click(self, event):
        jp = self._hit(event)
        if jp:
            self._open_plot(jp)

    def _open_plot(self, json_path: str):
        if self._on_plot_open:
            self._on_plot_open(json_path)

    def _placeholder(self):
        self._canvas.delete("all")
        self._canvas.create_text(140,100,text="No PDF yet.\n\nPress F5 to compile.",
                                  fill="#666",font=("Consolas",11),justify=tk.CENTER)

    def load(self,path):
        self._path=path; self._render()

    def _render(self):
        if not (HAS_FITZ and HAS_PIL): return
        if not self._path or not os.path.exists(self._path): return
        try: doc=fitz.open(self._path)
        except Exception: return
        self._canvas.delete("all"); self._imgs.clear(); self._plot_rects.clear()
        scale=self._zoom*1.5
        mat=fitz.Matrix(scale,scale)
        d=self._plots_dir(); y=12; max_w=0
        for page in doc:
            pix=page.get_pixmap(matrix=mat,alpha=False)
            img=Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
            photo=ImageTk.PhotoImage(img); self._imgs.append(photo)
            self._canvas.create_rectangle(14,y+3,14+pix.width+1,y+pix.height+1,fill="#111",outline="")
            self._canvas.create_image(12,y,anchor="nw",image=photo)
            if d:
                for lnk in page.get_links():
                    uri=lnk.get("uri","")
                    if uri.startswith("zrkplot://"):
                        r=lnk["from"]; idx=int(uri.split("://")[1])
                        jp=os.path.join(d,f"zrkplot_{idx:03d}.json")
                        if os.path.exists(jp):
                            self._plot_rects.append((12+r.x0*scale,y+r.y0*scale,
                                                     12+r.x1*scale,y+r.y1*scale,jp))
            y+=pix.height+18; max_w=max(max_w,pix.width)
        doc.close(); self._canvas.configure(scrollregion=(0,0,max_w+24,y))

    def _zoom_in(self):
        self._zoom=min(3.0,self._zoom+0.25); self._zlbl.config(text=f"{int(self._zoom*100)}%"); self._render()
    def _zoom_out(self):
        self._zoom=max(0.25,self._zoom-0.25); self._zlbl.config(text=f"{int(self._zoom*100)}%"); self._render()


class App:
    def __init__(self):
        self.filepath=None; self.dirty=False; self._hl_job=None
        self.root=tk.Tk(); self.root.title("zrktex")
        self.root.geometry("1280x800"); self.root.configure(bg=T["bg"])
        self.root.protocol("WM_DELETE_WINDOW",self._quit)
        self._apply_style(); self._build_menu(); self._build_toolbar()
        self._paned=ttk.PanedWindow(self.root,orient=tk.HORIZONTAL)
        self._paned.pack(fill=tk.BOTH,expand=True)
        ed_frame=tk.Frame(self._paned,bg=T["bg"])
        self._paned.add(ed_frame,weight=3)
        self._build_editor(ed_frame)
        self.pdf=PDFViewer(self._paned,on_plot_open=self._open_plot_viewer); self._paned.add(self.pdf,weight=2)
        self._build_statusbar(); self._build_output()
        self._ac=AutoComplete(self.editor,self.root)
        self._bind()
        _flags = {"--tui", "--plots"}
        _file_args = [a for a in sys.argv[1:] if a not in _flags]
        if _file_args:
            path = _file_args[-1]
            if path: self._open_file(path)
            else: self._new_template()
        else:
            self._new_template()

    def _apply_style(self):
        s=ttk.Style(); s.theme_use("clam")
        s.configure("TFrame",background=T["bg"])
        s.configure("TPanedwindow",background=T["sash"])
        s.configure("Sash",sashthickness=5,sashpad=2)
        for o in ("Vertical","Horizontal"):
            s.configure(f"{o}.TScrollbar",troughcolor=T["bg"],background=T["tbar"],arrowcolor=T["ln_fg"])

    def _build_menu(self):
        def menu(p):
            return tk.Menu(p,bg=T["tbar"],fg=T["fg"],activebackground=T["sel"],
                           activeforeground=T["fg"],bd=0,tearoff=False)
        mb=menu(self.root); self.root.config(menu=mb)
        fm=menu(mb); mb.add_cascade(label="File",menu=fm)
        fm.add_command(label="New          Ctrl+N",command=self._new)
        fm.add_command(label="Open…        Ctrl+O",command=self._open_dialog)
        fm.add_command(label="Save         Ctrl+S",command=self._save)
        fm.add_command(label="Save As…  Ctrl+Shift+S",command=self._save_as)
        fm.add_separator(); fm.add_command(label="Quit  Ctrl+Q",command=self._quit)
        em=menu(mb); mb.add_cascade(label="Edit",menu=em)
        em.add_command(label="Undo  Ctrl+Z",command=lambda:self.editor.event_generate("<<Undo>>"))
        em.add_command(label="Redo  Ctrl+Y",command=lambda:self.editor.event_generate("<<Redo>>"))
        em.add_separator(); em.add_command(label="Find  Ctrl+F",command=self._find_dialog)
        lm=menu(mb); mb.add_cascade(label="LaTeX",menu=lm)
        lm.add_command(label="Compile         F5",command=self._compile)
        lm.add_command(label="Compile & View  F6",command=self._compile_view)
        lm.add_separator()
        lm.add_command(label=r"Insert \begin{}",command=self._insert_begin)
        lm.add_command(label="Insert equation",command=self._insert_equation)
        lm.add_command(label=r"Insert \frac{}{}",command=self._insert_frac)
        lm.add_separator()
        lm.add_command(label=r"Insert \plot — 2-D",         command=lambda:self._insert_plot("2d"))
        lm.add_command(label=r"Insert \plot — parametric",  command=lambda:self._insert_plot("parametric"))
        lm.add_command(label=r"Insert \plot — 3-D surface",  command=lambda:self._insert_plot("3d"))
        lm.add_command(label=r"Insert \plot — complex",     command=lambda:self._insert_plot("complex"))
        lm.add_command(label=r"Insert \plot — vector field", command=lambda:self._insert_plot("vector"))
        vm=menu(mb); mb.add_cascade(label="View",menu=vm)
        vm.add_command(label="Toggle PDF    F7",command=self._toggle_pdf)
        vm.add_command(label="Toggle output F8",command=self._toggle_output)

    def _build_toolbar(self):
        tb=tk.Frame(self.root,bg=T["tbar"],height=34); tb.pack(fill=tk.X,side=tk.TOP); tb.pack_propagate(False)
        def tbtn(text,cmd):
            b=tk.Button(tb,text=text,command=cmd,bg=T["tbar"],fg=T["fg"],
                        activebackground=T["sel"],activeforeground=T["fg"],
                        relief=tk.FLAT,font=FONT_UI,padx=10,pady=5,bd=0)
            b.pack(side=tk.LEFT,padx=1,pady=2); return b
        tbtn("New",self._new); tbtn("Open",self._open_dialog); tbtn("Save",self._save)
        tk.Frame(tb,bg="#555",width=1).pack(side=tk.LEFT,fill=tk.Y,padx=6,pady=6)
        tbtn("▶  Compile",self._compile); tbtn("▶▶ Compile+View",self._compile_view)
        self._compile_lbl=tk.Label(tb,text="",bg=T["tbar"],fg=T["ok"],font=FONT_UI)
        self._compile_lbl.pack(side=tk.LEFT,padx=10)

    def _build_editor(self,parent):
        wrap=tk.Frame(parent,bg=T["bg"]); wrap.pack(fill=tk.BOTH,expand=True)
        vsb=ttk.Scrollbar(wrap,orient=tk.VERTICAL)
        hsb=ttk.Scrollbar(parent,orient=tk.HORIZONTAL)
        self.editor=tk.Text(wrap,bg=T["bg"],fg=T["fg"],insertbackground=T["fg"],
                             selectbackground=T["sel"],font=FONT,wrap=tk.NONE,
                             undo=True,maxundo=-1,bd=0,highlightthickness=0,
                             padx=8,pady=6,spacing1=1,spacing3=1,
                             yscrollcommand=vsb.set,xscrollcommand=hsb.set)
        vsb.config(command=self._yview_proxy); hsb.config(command=self.editor.xview)
        hsb.pack(side=tk.BOTTOM,fill=tk.X)
        self.lnum=LineNumbers(wrap,self.editor); self.lnum.pack(side=tk.LEFT,fill=tk.Y)
        vsb.pack(side=tk.RIGHT,fill=tk.Y); self.editor.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
        for tag,fg in [("num",T["num"]),("brc",T["brc"]),("mth",T["mth"]),
                       ("cmd",T["cmd"]),("cmt",T["cmt"])]:
            self.editor.tag_configure(tag,foreground=fg)
        self.editor.tag_configure("match",background="#2d4f1e",foreground=T["fg"])
        self.editor.tag_configure("match_cur",background=T["sel"],foreground="#ffffff")
        self.editor.tag_configure("err_line",background=T["err_bg"],underline=True)
        self.editor.tag_raise("cmt")

    # The scrollbar's yscrollcommand fires this instead of editor.yview directly so that
    # the line-number canvas repaints whenever the text view scrolls.
    def _yview_proxy(self,*a): self.editor.yview(*a); self.lnum._redraw()

    def _build_statusbar(self):
        sb=tk.Frame(self.root,bg=T["stat"],height=22); sb.pack(fill=tk.X,side=tk.BOTTOM); sb.pack_propagate(False)
        self._lbl_file=tk.Label(sb,text="untitled.tex",bg=T["stat"],fg=T["stat_fg"],font=FONT_UI,padx=10)
        self._lbl_file.pack(side=tk.LEFT)
        self._lbl_dirty=tk.Label(sb,text="",bg=T["stat"],fg=T["stat_fg"],font=FONT_UI,padx=4)
        self._lbl_dirty.pack(side=tk.LEFT)
        self._lbl_pos=tk.Label(sb,text="Ln 1, Col 1",bg=T["stat"],fg=T["stat_fg"],font=FONT_UI,padx=10)
        self._lbl_pos.pack(side=tk.RIGHT)

    def _build_output(self):
        self._out_frame=tk.Frame(self.root,bg=T["out_bg"]); self._out_frame.pack(fill=tk.X,side=tk.BOTTOM)
        hdr=tk.Frame(self._out_frame,bg=T["tbar"],height=20); hdr.pack(fill=tk.X); hdr.pack_propagate(False)
        tk.Label(hdr,text="Compile Output",bg=T["tbar"],fg=T["ln_fg"],font=("Segoe UI",8)).pack(side=tk.LEFT,padx=8)
        tk.Button(hdr,text="×",command=self._toggle_output,bg=T["tbar"],fg=T["ln_fg"],
                  relief=tk.FLAT,font=("Segoe UI",8),padx=3,pady=0).pack(side=tk.RIGHT,padx=3)
        self._out_text=tk.Text(self._out_frame,bg=T["out_bg"],fg="#9cdcfe",font=("Consolas",9),
                                height=7,state=tk.DISABLED,bd=0,highlightthickness=0,padx=8,pady=4)
        self._out_text.tag_configure("ok",foreground=T["ok"])
        self._out_text.tag_configure("err",foreground=T["err"])
        self._out_text.tag_configure("errlink",foreground=T["err"],underline=True)
        self._out_text.pack(fill=tk.X); self._out_visible=True
        # Double-click on a line containing "l.NN" jumps to that line in the editor
        self._out_text.bind("<Double-Button-1>", self._on_output_click)

    def _toggle_output(self,*_):
        if self._out_visible: self._out_frame.pack_forget()
        else: self._out_frame.pack(fill=tk.X,side=tk.BOTTOM,before=self._paned)
        self._out_visible=not self._out_visible

    def _toggle_pdf(self,*_):
        panes=list(self._paned.panes())
        if str(self.pdf) in panes: self._paned.forget(self.pdf)
        else: self._paned.add(self.pdf,weight=2)

    def _bind(self):
        r,e=self.root,self.editor
        r.bind("<Control-n>",lambda _:self._new())
        r.bind("<Control-o>",lambda _:self._open_dialog())
        r.bind("<Control-s>",lambda _:self._save())
        r.bind("<Control-S>",lambda _:self._save_as())
        r.bind("<Control-q>",lambda _:self._quit())
        r.bind("<Control-f>",lambda _:self._find_dialog())
        r.bind("<F5>",lambda _:self._compile())
        r.bind("<F6>",lambda _:self._compile_view())
        r.bind("<F7>",lambda _:self._toggle_pdf())
        r.bind("<F8>",lambda _:self._toggle_output())
        e.bind("<<Modified>>",self._on_modified)
        e.bind("<ButtonRelease>",self._update_pos)
        e.bind("<Tab>",self._on_tab,add=True)
        e.bind("<Escape>",self._on_escape,add=True)
        e.bind("<Down>",self._on_down,add=True)
        e.bind("<Up>",self._on_up,add=True)
        e.bind("<Return>",self._on_return)
        e.bind("<KeyRelease>",self._on_keyrelease,add=True)
        e.bind("{",lambda _:self._pair("{","}"))
        e.bind("(",lambda _:self._pair("(",")" ))
        e.bind("[",lambda _:self._pair("[","]"))
        e.bind("$",lambda _:self._pair("$","$"))

    def _on_modified(self,_=None):
        if self.editor.edit_modified():
            if not self.dirty: self.dirty=True; self._update_title()
            self._schedule_highlight(); self.editor.edit_modified(False)

    def _on_keyrelease(self,event):
        self._update_pos()
        if event.keysym in ("BackSlash","BackSpace") or (event.char and event.char.isalpha()):
            self._ac.update()

    def _on_tab(self,_):
        if self._ac.visible(): self._ac.apply(); return "break"
    def _on_escape(self,_):
        if self._ac.visible(): self._ac.hide(); return "break"
    def _on_down(self,_):
        if self._ac.visible(): self._ac.move(1); return "break"
    def _on_up(self,_):
        if self._ac.visible(): self._ac.move(-1); return "break"
    def _on_return(self,_):
        if self._ac.visible(): self._ac.apply(); return "break"
        self._auto_indent(); return "break"

    def _pair(self,o,c):
        self.editor.insert(tk.INSERT,o+c)
        self.editor.mark_set(tk.INSERT,f"{self.editor.index(tk.INSERT)}-1c")
        return "break"

    def _auto_indent(self):
        line=self.editor.get("insert linestart","insert lineend")
        indent=len(line)-len(line.lstrip()); stripped=line.rstrip()
        extra=4 if (stripped.endswith("{") or re.search(r"\\begin\{[^}]*\}\s*$",stripped)) else 0
        self.editor.insert(tk.INSERT,"\n"+" "*(indent+extra))
        self.editor.see(tk.INSERT)

    def _new(self):
        if self.dirty and not self._confirm_discard(): return
        self.editor.delete("1.0",tk.END); self.filepath=None; self.dirty=False
        self._new_template()

    def _new_template(self):
        tmpl=(r"\documentclass{article}"+"\n"+r"\usepackage[utf8]{inputenc}"+"\n"
              +r"\usepackage{amsmath}"+"\n"+r"\usepackage{amssymb}"+"\n"+"\n"
              +r"\title{Untitled}"+"\n"+r"\author{}"+"\n"+r"\date{\today}"+"\n"+"\n"
              +r"\begin{document}"+"\n"+r"\maketitle"+"\n"+"\n"+r"\end{document}"+"\n")
        self.editor.delete("1.0",tk.END); self.editor.insert("1.0",tmpl)
        self.editor.edit_reset(); self.dirty=False; self._update_title(); self._highlight()

    def _open_dialog(self):
        path=filedialog.askopenfilename(filetypes=[("LaTeX files","*.tex"),("All files","*.*")])
        if path: self._open_file(path)

    def _open_file(self,path):
        if self.dirty and not self._confirm_discard(): return
        try: text=Path(path).read_text(encoding="utf-8")
        except Exception as ex: messagebox.showerror("Open error",str(ex)); return
        self.editor.delete("1.0",tk.END); self.editor.insert("1.0",text)
        self.editor.edit_reset(); self.filepath=path; self.dirty=False
        self._update_title(); self._highlight()
        pdf=str(Path(path).with_suffix(".pdf"))
        if os.path.exists(pdf) and HAS_FITZ and HAS_PIL: self.pdf.load(pdf)

    def _save(self):
        if self.filepath is None: return self._save_as()
        self._do_save(self.filepath)

    def _save_as(self):
        path=filedialog.asksaveasfilename(defaultextension=".tex",
                                           filetypes=[("LaTeX files","*.tex"),("All files","*.*")])
        if path: self.filepath=path; self._do_save(path)

    def _do_save(self,path):
        try: Path(path).write_text(self.editor.get("1.0","end-1c"),encoding="utf-8")
        except Exception as ex: messagebox.showerror("Save error",str(ex)); return
        self.dirty=False; self._update_title()

    def _confirm_discard(self): return messagebox.askyesno("Unsaved changes","Discard unsaved changes?")

    def _quit(self):
        if self.dirty and not self._confirm_discard(): return
        self.root.destroy()

    def _compile(self,open_pdf=False):
        if self.filepath is None:
            messagebox.showinfo("Save first","Save the file before compiling.")
            path=filedialog.asksaveasfilename(defaultextension=".tex",
                                               filetypes=[("LaTeX files","*.tex"),("All files","*.*")])
            if not path: return
            self.filepath=path; self._do_save(path)
        self._save()
        self._clear_error_highlights()   # remove stale highlights from previous compile
        self._set_out("Compiling…\n")
        self._compile_lbl.config(text="Compiling…",fg="#ffd700")
        threading.Thread(target=self._run_compile,args=(self.filepath,open_pdf),daemon=True).start()

    def _compile_view(self): self._compile(open_pdf=True)

    def _run_compile(self,path,open_pdf):
        compiler=_find_compiler()
        if not compiler:
            self._append_out("No LaTeX compiler found.\n","err")
            self.root.after(0,lambda:self._compile_lbl.config(text="No compiler",fg=T["err"])); return
        cwd=str(Path(path).parent)
        # Plot preprocessing
        compile_path,proc_tex,n_plots=_preprocess_plots(path)
        if n_plots: self._append_out(f"Preprocessed {n_plots} plot(s).\n","ok")
        elif r"\plot" in Path(path).read_text(encoding="utf-8") and not HAS_MPL:
            self._append_out("Warning: \\plot found but matplotlib unavailable.\n","err")
        cmd=_build_cmd(compiler,compile_path)
        try:
            res=subprocess.run(cmd,cwd=cwd,capture_output=True,text=True,timeout=120)
        except subprocess.TimeoutExpired:
            self._append_out("Compilation timed out.\n","err"); return
        except Exception as ex:
            self._append_out(f"Error: {ex}\n","err"); return
        out=res.stdout+res.stderr; self._append_out(out)
        if proc_tex: _cleanup_processed(proc_tex,path)
        pdf_path=str(Path(path).with_suffix(".pdf"))
        # pdflatex sometimes exits non-zero even when it produced a usable PDF, so also
        # treat a present PDF as success (latexmk behaves similarly on recoverable errors)
        ok=res.returncode==0 or os.path.exists(pdf_path)

        # Parse errors from log and highlight them in the editor
        errors = _parse_log_errors(out)
        if errors:
            self.root.after(0, lambda e=errors: self._apply_error_highlights(e))
        else:
            self.root.after(0, self._clear_error_highlights)

        if ok:
            self._append_out("\n✓ Compiled successfully.\n","ok")
            self.root.after(0,lambda:self._compile_lbl.config(text="✓ Compiled",fg=T["ok"]))
            self.root.after(0,lambda:self.pdf.load(pdf_path))
            if open_pdf: self.root.after(0,lambda:_open_pdf_file(pdf_path))
            # Update Plots ▾ button visibility (--plots mode)
            plots_dir = str(Path(path).parent / "_zrkplots")
            self.root.after(0, lambda d=plots_dir: self.pdf.set_plots_dir(d))
        else:
            errs=[l for l in out.splitlines() if l.startswith("!")]
            msg=errs[0] if errs else "Compilation failed."
            self._append_out(f"\n✗ {msg}\n","err")
            # Tag "l.NN" occurrences in the output panel as clickable error links
            self._tag_output_error_links()
            self.root.after(0,lambda:self._compile_lbl.config(text="✗ Error",fg=T["err"]))

    # Debounce highlighting — cancel any pending rehighlight and restart the timer.
    # 250 ms is long enough that typing quickly doesn't trigger a full re-tag every keystroke.
    def _schedule_highlight(self):
        if self._hl_job: self.root.after_cancel(self._hl_job)
        self._hl_job=self.root.after(250,self._highlight)

    def _highlight(self):
        self._hl_job=None; text=self.editor.get("1.0","end-1c")
        for tag in ("cmd","cmt","brc","num","mth"): self.editor.tag_remove(tag,"1.0",tk.END)
        def apply(pat,tag,flags=0):
            for m in re.finditer(pat,text,flags):
                self.editor.tag_add(tag,f"1.0+{m.start()}c",f"1.0+{m.end()}c")
        apply(r"\b\d+\.?\d*\b","num")
        apply(r"[{}\[\]]","brc")
        apply(r"\$\$[\s\S]*?\$\$|\$[^$\n]*\$","mth")
        apply(r"\\[a-zA-Z@]+\*?","cmd")
        apply(r"%[^\n]*","cmt")
        # Comments must win over commands — raise "cmt" last so \% stays green, not cyan
        self.editor.tag_raise("cmt")

    def _insert_begin(self):
        self.editor.insert(tk.INSERT,r"\begin{}"+"\n\n"+r"\end{}")
        pos=self.editor.search("{}","insert-25c","insert+1c")
        if pos: self.editor.mark_set(tk.INSERT,f"{pos}+1c")

    def _insert_equation(self):
        self.editor.insert(tk.INSERT,r"\begin{equation}"+"\n    \n"+r"\end{equation}")

    def _insert_frac(self):
        self.editor.insert(tk.INSERT,r"\frac{}{}")

    def _insert_plot(self,ptype):
        snippets={
            "2d":        r"\plot[xmin=-5, xmax=5]{sin(x)}",
            "parametric":r"\plot[type=parametric, tmin=0, tmax=6.283]{cos(t), sin(t)}",
            "3d":        r"\plot[type=3d, xmin=-3, xmax=3, ymin=-3, ymax=3]{sin(x)*cos(y)}",
            "complex":   r"\plot[type=complex, xmin=-2, xmax=2, ymin=-2, ymax=2]{z**2 - 1}",
            "vector":    r"\plot[type=vector, xmin=-3, xmax=3, ymin=-3, ymax=3]{-y, x}",
        }
        self.editor.insert(tk.INSERT,snippets.get(ptype,r"\plot{}"))

    def _find_dialog(self):
        dlg=tk.Toplevel(self.root); dlg.title("Find"); dlg.geometry("340x38")
        dlg.configure(bg=T["tbar"]); dlg.resizable(False,False); dlg.transient(self.root)
        tk.Label(dlg,text="Find:",bg=T["tbar"],fg=T["fg"],font=FONT_UI).pack(side=tk.LEFT,padx=8)
        ent=tk.Entry(dlg,bg=T["bg"],fg=T["fg"],insertbackground=T["fg"],font=FONT_SM,relief=tk.FLAT,bd=2)
        ent.pack(side=tk.LEFT,fill=tk.X,expand=True,padx=4,pady=4)
        self._find_idx=0; self._find_ranges=[]
        def do_find(*_):
            pat=ent.get()
            self.editor.tag_remove("match","1.0",tk.END); self.editor.tag_remove("match_cur","1.0",tk.END)
            self._find_ranges=[]
            if not pat: return
            start="1.0"
            while True:
                pos=self.editor.search(pat,start,tk.END,regexp=True)
                if not pos: break
                end=f"{pos}+{len(pat)}c"; self.editor.tag_add("match",pos,end)
                self._find_ranges.append((pos,end)); start=end
            if self._find_ranges:
                self._find_idx=0; p,e2=self._find_ranges[0]
                self.editor.tag_add("match_cur",p,e2); self.editor.mark_set(tk.INSERT,p); self.editor.see(p)
        def do_next(*_):
            if not self._find_ranges: do_find(); return
            self.editor.tag_remove("match_cur","1.0",tk.END)
            self._find_idx=(self._find_idx+1)%len(self._find_ranges)
            p,e2=self._find_ranges[self._find_idx]
            self.editor.tag_add("match_cur",p,e2); self.editor.mark_set(tk.INSERT,p); self.editor.see(p)
        tk.Button(dlg,text="Find",command=do_find,bg=T["tbar"],fg=T["fg"],relief=tk.FLAT,font=FONT_UI,padx=8).pack(side=tk.LEFT,padx=2)
        tk.Button(dlg,text="Next",command=do_next,bg=T["tbar"],fg=T["fg"],relief=tk.FLAT,font=FONT_UI,padx=8).pack(side=tk.LEFT,padx=2)
        ent.bind("<Return>",do_find); ent.focus_set()

    def _set_out(self,text,tag=""):
        def _do():
            self._out_text.config(state=tk.NORMAL); self._out_text.delete("1.0",tk.END)
            self._out_text.insert(tk.END,text,tag); self._out_text.config(state=tk.DISABLED)
        self.root.after(0,_do)

    # Compilation runs on a background thread, so all widget updates must be
    # marshalled back to the main thread via root.after(0, ...).
    def _append_out(self,text,tag=""):
        def _do():
            self._out_text.config(state=tk.NORMAL); self._out_text.insert(tk.END,text,tag)
            self._out_text.config(state=tk.DISABLED); self._out_text.see(tk.END)
        self.root.after(0,_do)

    # ── Error highlighting ─────────────────────────────────────────────────────

    def _apply_error_highlights(self, errors):
        """Paint a red background on every line that pdflatex reported an error on."""
        self.editor.tag_remove("err_line", "1.0", tk.END)
        for line_no, _msg in errors:
            self.editor.tag_add("err_line", f"{line_no}.0", f"{line_no}.end")
        # Scroll to the first error
        if errors:
            self.editor.see(f"{errors[0][0]}.0")

    def _clear_error_highlights(self):
        self.editor.tag_remove("err_line", "1.0", tk.END)

    def _tag_output_error_links(self):
        """Underline 'l.NN' tokens in the compile output so they look clickable."""
        def _do():
            self._out_text.config(state=tk.NORMAL)
            text = self._out_text.get("1.0", tk.END)
            for m in re.finditer(r"l\.(\d+)", text):
                s = f"1.0+{m.start()}c"
                e = f"1.0+{m.end()}c"
                self._out_text.tag_add("errlink", s, e)
            self._out_text.config(state=tk.DISABLED)
        self.root.after(0, _do)

    def _on_output_click(self, event):
        """Double-click on 'l.NN' in the output panel → jump to that line in editor."""
        idx = self._out_text.index(f"@{event.x},{event.y}")
        line_text = self._out_text.get(f"{idx} linestart", f"{idx} lineend")
        m = re.search(r"l\.(\d+)", line_text)
        if m:
            line_no = int(m.group(1))
            self.editor.mark_set(tk.INSERT, f"{line_no}.0")
            self.editor.see(f"{line_no}.0")
            self.editor.focus_set()

    # ── Interactive plot viewer ────────────────────────────────────────────────

    def _open_plot_viewer(self, json_path: str):
        try:
            data = _json.loads(Path(json_path).read_text())
        except Exception as ex:
            messagebox.showerror("Plot error", f"Could not read plot data:\n{ex}", parent=self.root)
            return
        expr  = data.get("expr_raw", "")
        ptype = data.get("type", "2d")
        opts  = {k.strip(): v.strip()
                 for part in data.get("opts_raw", "").split(",")
                 if "=" in part
                 for k, v in [part.split("=", 1)]}

        # Build a WolframAlpha query from the plot type and expression
        if ptype in ("parametric", "param"):
            query = f"parametric plot {expr}"
        elif ptype in ("3d", "surface"):
            query = f"plot {expr}"
        elif ptype in ("curve3d", "parametric3d"):
            query = f"3d parametric plot {expr}"
        elif ptype == "vector":
            query = f"vector field {expr}"
        elif ptype == "complex":
            query = f"plot {expr}"
        else:  # 2d
            xmin = opts.get("xmin", "-10")
            xmax = opts.get("xmax",  "10")
            query = f"plot {expr} from {xmin} to {xmax}"

        url = "https://www.wolframalpha.com/input?" + urllib.parse.urlencode({"i": query})
        try:
            webbrowser.open(url)
        except Exception as ex:
            messagebox.showerror("Plot error", f"Could not open browser:\n{ex}", parent=self.root)

    # ── Status / position ─────────────────────────────────────────────────────

    def _update_title(self):
        name=Path(self.filepath).name if self.filepath else "untitled.tex"
        self.root.title(f"zrktex — {name}{' ●' if self.dirty else ''}")
        self._lbl_file.config(text=name); self._lbl_dirty.config(text="●" if self.dirty else "")

    def _update_pos(self,*_):
        row,col=self.editor.index(tk.INSERT).split(".")
        self._lbl_pos.config(text=f"Ln {row}, Col {int(col)+1}")

    def run(self): self.root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
def main():
    args = [a for a in sys.argv[1:] if a not in ("--tui", "--plots")]
    filename = args[0] if args else None

    if _TUI_MODE:
        if not HAS_CURSES:
            print("curses not available — try: pip install windows-curses"); sys.exit(1)
        Editor(filename).run()
    else:
        App().run()

if __name__ == "__main__":
    main()
