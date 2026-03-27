#!/usr/bin/env python3
"""
LaTeX Vim Editor
A vim-like TUI editor that compiles LaTeX to PDF on :wq

Usage:  python editor.py [file.tex]

Normal mode keys:
  h/j/k/l       Move left/down/up/right
  w/b/e         Word forward/backward/end
  0 / $         Line start/end
  ^             First non-blank character
  gg / G        File start/end
  Ctrl+D/U      Half-page down/up
  i/I           Insert before cursor / line start
  a/A           Append after cursor / line end
  o/O           Open new line below/above
  x             Delete char under cursor
  dd            Delete line
  D             Delete to end of line
  yy / Y        Yank line
  p / P         Paste below/above
  J             Join line with next
  u             Undo
  Ctrl+R        Redo
  /             Search forward
  n / N         Next/previous match
  v             Visual line mode
  :             Command mode

Command mode:
  :w            Save
  :q            Quit (fails if unsaved)
  :q!           Force quit
  :wq / :x      Save + compile PDF + quit
  :pdf          Save + compile PDF (stay open)
  :e <file>     Open file

Insert mode:
  ESC           Return to Normal
  Tab           Autocomplete or indent (4 spaces)
  Backspace     Delete left / join lines
  Enter         New line with auto-indent + auto-pair closing
"""

import sys
import os
import re
import subprocess
import platform
from copy import deepcopy
from enum import Enum
from typing import List, Tuple, Optional

# ── Bootstrap dependencies ────────────────────────────────────────────────────
def _pip(pkg):
    subprocess.run([sys.executable, "-m", "pip", "install", pkg], check=True)

try:
    import curses
    import curses.ascii
except ImportError:
    _pip("windows-curses")
    import curses
    import curses.ascii

try:
    from pygments.lexers.markup import TexLexer
    from pygments.token import Token
    _TEX_LEXER = TexLexer()
    HAS_PYGMENTS = True
except ImportError:
    HAS_PYGMENTS = False
    _TEX_LEXER = None

# ── Mode ──────────────────────────────────────────────────────────────────────
class Mode(Enum):
    NORMAL  = "NORMAL"
    INSERT  = "INSERT"
    COMMAND = "COMMAND"
    VISUAL  = "VISUAL"

# ── Color pair IDs ────────────────────────────────────────────────────────────
C_DEFAULT  = 1
C_KEYWORD  = 2   # \commands  → cyan
C_COMMENT  = 3   # % comments → green
C_STRING   = 4   # {braces}   → yellow
C_NUMBER   = 5   # numbers    → magenta
C_PUNCT    = 6   # []()$&     → red
C_STATUS   = 7   # status bar → black on white
C_LINENO   = 8   # line nums  → dark
C_COMPLETE = 9   # popup bg   → black on cyan
C_COMP_SEL = 10  # popup sel  → black on white
C_SEARCH   = 11  # search hit → black on yellow
C_VISUAL   = 12  # visual sel → reverse

def _init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_DEFAULT,  curses.COLOR_WHITE,   -1)
    curses.init_pair(C_KEYWORD,  curses.COLOR_CYAN,    -1)
    curses.init_pair(C_COMMENT,  curses.COLOR_GREEN,   -1)
    curses.init_pair(C_STRING,   curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_NUMBER,   curses.COLOR_MAGENTA, -1)
    curses.init_pair(C_PUNCT,    curses.COLOR_RED,     -1)
    curses.init_pair(C_STATUS,   curses.COLOR_BLACK,   curses.COLOR_WHITE)
    curses.init_pair(C_LINENO,   curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_COMPLETE, curses.COLOR_BLACK,   curses.COLOR_CYAN)
    curses.init_pair(C_COMP_SEL, curses.COLOR_BLACK,   curses.COLOR_WHITE)
    curses.init_pair(C_SEARCH,   curses.COLOR_BLACK,   curses.COLOR_YELLOW)
    curses.init_pair(C_VISUAL,   curses.COLOR_BLACK,   curses.COLOR_WHITE)

def _tok_cp(ttype) -> int:
    if not HAS_PYGMENTS:
        return C_DEFAULT
    if ttype in Token.Comment:
        return C_COMMENT
    if ttype in Token.Keyword or ttype in Token.Name.Builtin or \
       ttype in Token.Name.Function or ttype in Token.Name.Tag:
        return C_KEYWORD
    if ttype in Token.Literal.String or ttype in Token.String:
        return C_STRING
    if ttype in Token.Literal.Number or ttype in Token.Number:
        return C_NUMBER
    if ttype in Token.Operator or ttype in Token.Punctuation:
        return C_PUNCT
    return C_DEFAULT

# ── LaTeX command list ────────────────────────────────────────────────────────
LATEX_COMMANDS = sorted([
    r"\begin", r"\end", r"\documentclass", r"\usepackage",
    r"\textbf", r"\textit", r"\texttt", r"\textrm", r"\textsf",
    r"\emph", r"\underline", r"\text", r"\mbox", r"\hbox", r"\vbox",
    r"\section", r"\subsection", r"\subsubsection",
    r"\paragraph", r"\subparagraph",
    r"\label", r"\ref", r"\eqref", r"\pageref", r"\nameref",
    r"\cite", r"\citep", r"\citet", r"\citealt", r"\citeauthor",
    r"\bibliography", r"\bibliographystyle", r"\addbibresource",
    r"\includegraphics", r"\caption", r"\subcaption", r"\centering",
    r"\frac", r"\dfrac", r"\tfrac", r"\cfrac",
    r"\sqrt", r"\sum", r"\int", r"\iint", r"\iiint", r"\oint",
    r"\prod", r"\coprod", r"\lim", r"\sup", r"\inf", r"\max", r"\min",
    r"\alpha", r"\beta", r"\gamma", r"\delta", r"\epsilon", r"\varepsilon",
    r"\zeta", r"\eta", r"\theta", r"\vartheta", r"\iota", r"\kappa",
    r"\lambda", r"\mu", r"\nu", r"\xi", r"\pi", r"\varpi",
    r"\rho", r"\varrho", r"\sigma", r"\varsigma", r"\tau",
    r"\upsilon", r"\phi", r"\varphi", r"\chi", r"\psi", r"\omega",
    r"\Gamma", r"\Delta", r"\Theta", r"\Lambda", r"\Xi",
    r"\Pi", r"\Sigma", r"\Upsilon", r"\Phi", r"\Psi", r"\Omega",
    r"\left", r"\right", r"\middle",
    r"\big", r"\Big", r"\bigg", r"\Bigg",
    r"\bigl", r"\bigr", r"\Bigl", r"\Bigr",
    r"\vspace", r"\hspace", r"\vspace*", r"\hspace*",
    r"\noindent", r"\indent", r"\par", r"\hline", r"\cline",
    r"\item", r"\maketitle", r"\tableofcontents", r"\listoffigures",
    r"\newpage", r"\clearpage", r"\pagebreak", r"\linebreak",
    r"\title", r"\author", r"\date", r"\thanks", r"\abstract",
    r"\mathbf", r"\mathrm", r"\mathit", r"\mathcal", r"\mathbb",
    r"\mathfrak", r"\mathsf", r"\mathtt",
    r"\overline", r"\underline", r"\widehat", r"\widetilde",
    r"\hat", r"\bar", r"\vec", r"\tilde", r"\dot", r"\ddot", r"\breve",
    r"\leq", r"\geq", r"\neq", r"\approx", r"\equiv", r"\sim", r"\cong",
    r"\ll", r"\gg", r"\prec", r"\succ", r"\preceq", r"\succeq",
    r"\cdot", r"\times", r"\div", r"\pm", r"\mp",
    r"\oplus", r"\otimes", r"\ominus", r"\oslash", r"\odot",
    r"\infty", r"\partial", r"\nabla", r"\forall", r"\exists", r"\nexists",
    r"\in", r"\notin", r"\ni", r"\subset", r"\supset",
    r"\subseteq", r"\supseteq", r"\nsubseteq",
    r"\cup", r"\cap", r"\setminus", r"\emptyset", r"\varnothing",
    r"\rightarrow", r"\leftarrow", r"\leftrightarrow",
    r"\Rightarrow", r"\Leftarrow", r"\Leftrightarrow",
    r"\longrightarrow", r"\longleftarrow",
    r"\mapsto", r"\longmapsto", r"\to", r"\gets",
    r"\uparrow", r"\downarrow", r"\updownarrow",
    r"\ldots", r"\cdots", r"\vdots", r"\ddots",
    r"\qquad", r"\quad",
    r"\newcommand", r"\renewcommand", r"\newenvironment", r"\renewenvironment",
    r"\def", r"\let", r"\newcounter", r"\setcounter", r"\addtocounter",
    r"\footnote", r"\footnotemark", r"\footnotetext",
    r"\input", r"\include", r"\includeonly",
    r"\tiny", r"\scriptsize", r"\footnotesize", r"\small",
    r"\normalsize", r"\large", r"\Large", r"\LARGE", r"\huge", r"\Huge",
    r"\bfseries", r"\itshape", r"\rmfamily", r"\sffamily", r"\ttfamily",
    r"\upshape", r"\mdseries", r"\scshape",
    r"\color", r"\textcolor", r"\colorbox", r"\fcolorbox", r"\pagecolor",
    r"\rule", r"\hrule", r"\vrule",
    r"\hfill", r"\vfill", r"\hfil", r"\vfil",
    r"\linewidth", r"\textwidth", r"\textheight",
    r"\baselineskip", r"\parskip", r"\parindent",
    r"\not", r"\neg", r"\land", r"\lor", r"\lnot",
    r"\sin", r"\cos", r"\tan", r"\log", r"\ln", r"\exp",
    r"\binom", r"\dbinom", r"\tbinom",
    r"\pmod", r"\pod", r"\mod", r"\gcd", r"\lcm",
    r"\matrix", r"\pmatrix", r"\bmatrix", r"\vmatrix", r"\Vmatrix",
    r"\cases", r"\dcases",
    r"\verb", r"\lstinputlisting",
    r"\index", r"\glossary",
    r"\centering", r"\raggedleft", r"\raggedright",
    r"\and", r"\thanks",
])

ENVIRONMENTS = sorted([
    "document", "abstract", "titlepage",
    "equation", "equation*", "align", "align*", "aligned",
    "gather", "gather*", "multline", "multline*", "split",
    "array", "matrix", "pmatrix", "bmatrix", "vmatrix", "Vmatrix",
    "cases", "dcases",
    "figure", "figure*", "table", "table*",
    "tabular", "tabular*", "tabularx", "longtable",
    "itemize", "enumerate", "description",
    "theorem", "lemma", "corollary", "proposition", "definition",
    "proof", "remark", "example", "exercise", "solution",
    "verbatim", "verbatim*", "lstlisting",
    "minipage", "center", "flushleft", "flushright",
    "quote", "quotation", "verse",
    "thebibliography",
    "tikzpicture", "scope", "axis",
    "frame",  # beamer
])

# ── Snapshot for undo ─────────────────────────────────────────────────────────
class _Snap:
    __slots__ = ("lines", "row", "col")
    def __init__(self, lines, row, col):
        self.lines = deepcopy(lines)
        self.row   = row
        self.col   = col

# ── Syntax cache ──────────────────────────────────────────────────────────────
class _HlCache:
    """Cache pygments tokenization; re-tokenize only when buffer changes."""
    def __init__(self):
        self._key   = None
        self._segs  = []   # list[list[tuple[str, int]]]  per-line segments

    def get(self, lines: List[str]):
        key = id(lines), len(lines), hash(tuple(lines))
        if key == self._key:
            return self._segs
        self._key  = key
        self._segs = self._tokenize(lines)
        return self._segs

    @staticmethod
    def _tokenize(lines):
        if not HAS_PYGMENTS:
            return [[(ln, C_DEFAULT)] for ln in lines]
        text = "\n".join(lines)
        try:
            raw = list(_TEX_LEXER.get_tokens(text))
        except Exception:
            return [[(ln, C_DEFAULT)] for ln in lines]
        # Split token stream back into per-line segments
        result: List[List[Tuple[str, int]]] = [[]]
        for ttype, val in raw:
            cp = _tok_cp(ttype)
            parts = val.split("\n")
            for i, part in enumerate(parts):
                if part:
                    result[-1].append((part, cp))
                if i < len(parts) - 1:
                    result.append([])
        # Trim trailing extra line pygments always adds
        while result and result[-1] == []:
            result.pop()
        # Ensure we have at least as many entries as lines
        while len(result) < len(lines):
            result.append([])
        return result

# ── Main editor ───────────────────────────────────────────────────────────────
class Editor:
    MAX_UNDO = 300

    def __init__(self, filename: Optional[str]):
        self.filename  = filename
        self.lines: List[str] = [""]
        self.row = self.col = 0
        self.top = self.left = 0        # scroll offsets
        self.mode  = Mode.NORMAL
        self.dirty = False

        # Command line
        self.cmd = ""                   # :command or /search buffer
        self.msg = ""                   # status message

        # Undo / redo
        self.undo_stack: List[_Snap] = []
        self.redo_stack: List[_Snap] = []

        # Visual mode
        self.vis_row = self.vis_col = 0

        # Search
        self.search_pat = ""
        self.matches: List[Tuple[int,int]] = []
        self.match_idx = 0

        # Autocomplete
        self.ac_list:   List[str] = []
        self.ac_idx:    int = -1
        self.ac_prefix: str = ""

        # Pending normal-mode keys
        self._pend   = ""    # "d", "y", "g", "c", "z"
        self._cnt    = ""    # digit accumulation

        # Yank register
        self.reg       = ""
        self.reg_lines = False

        # Syntax cache
        self._hl = _HlCache()

        if filename and os.path.exists(filename):
            self._load()
        elif filename:
            self._new_template()

    # ── File I/O ──────────────────────────────────────────────────────────────
    def _load(self):
        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                text = f.read()
            self.lines = text.splitlines() or [""]
            self.dirty = False
            self.msg   = f'"{self.filename}" loaded ({len(self.lines)} lines)'
        except Exception as e:
            self.msg = f"Error loading: {e}"

    def _new_template(self):
        """Populate a new .tex file with minimal boilerplate."""
        self.lines = [
            r"\documentclass[12pt]{article}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage{amsmath, amssymb}",
            r"\usepackage{geometry}",
            r"\usepackage{graphicx}",
            r"\usepackage{hyperref}",
            r"\geometry{margin=1in}",
            r"",
            r"\begin{document}",
            r"",
            r"",
            r"\end{document}",
        ]
        self.dirty = True
        # Place cursor on the blank line inside the document, ready to write
        self.row = 11
        self.col = 0
        self.msg = f'New file "{self.filename}"'

    def _save(self) -> bool:
        if not self.filename:
            self.msg = 'No filename — use :w <name>'
            return False
        try:
            with open(self.filename, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(self.lines) + "\n")
            self.dirty = False
            self.msg   = f'"{self.filename}" written ({len(self.lines)} lines)'
            return True
        except Exception as e:
            self.msg = f"Write error: {e}"
            return False

    def _compile(self) -> bool:
        if not self.filename:
            self.msg = "No filename to compile."
            return False
        wd  = os.path.dirname(os.path.abspath(self.filename)) or "."
        fp  = os.path.abspath(self.filename)
        import shutil
        compilers = []
        for c, args in [
            ("pdflatex", ["-interaction=nonstopmode", "-halt-on-error"]),
            ("latexmk",  ["-pdf", "-interaction=nonstopmode"]),
            ("tectonic", []),
        ]:
            if shutil.which(c):
                compilers.append([c] + args + [fp])
        if not compilers:
            self.msg = "No LaTeX compiler found (install pdflatex / MiKTeX / TeX Live)."
            return False
        cmd = compilers[0]
        self.msg = f"Compiling with {cmd[0]}…"
        try:
            r = subprocess.run(cmd, cwd=wd, capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                self.msg = "Compiled OK!"
                return True
            # Extract meaningful error from stdout
            out = r.stdout or r.stderr or ""
            errs = [ln for ln in out.splitlines() if ln.startswith("!")]
            if errs:
                self.msg = "Error: " + errs[0][:80]
            else:
                self.msg = "Compile failed (check .log file)."
            return False
        except subprocess.TimeoutExpired:
            self.msg = "Compile timed out."
            return False
        except Exception as e:
            self.msg = f"Compile error: {e}"
            return False

    def _open_pdf(self):
        if not self.filename:
            return
        pdf = os.path.splitext(os.path.abspath(self.filename))[0] + ".pdf"
        if not os.path.exists(pdf):
            return
        try:
            if platform.system() == "Windows":
                os.startfile(pdf)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", pdf])
            else:
                subprocess.Popen(["xdg-open", pdf])
        except Exception:
            pass

    # ── Undo / Redo ───────────────────────────────────────────────────────────
    def _push(self):
        """Snapshot current state onto undo stack."""
        self.undo_stack.append(_Snap(self.lines, self.row, self.col))
        if len(self.undo_stack) > self.MAX_UNDO:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _undo(self):
        if not self.undo_stack:
            self.msg = "Already at oldest change."; return
        self.redo_stack.append(_Snap(self.lines, self.row, self.col))
        s = self.undo_stack.pop()
        self.lines, self.row, self.col = s.lines, s.row, s.col
        self.dirty = True
        self._clamp()

    def _redo(self):
        if not self.redo_stack:
            self.msg = "Already at newest change."; return
        self.undo_stack.append(_Snap(self.lines, self.row, self.col))
        s = self.redo_stack.pop()
        self.lines, self.row, self.col = s.lines, s.row, s.col
        self.dirty = True
        self._clamp()

    # ── Cursor helpers ────────────────────────────────────────────────────────
    def _clamp(self):
        self.row = max(0, min(self.row, len(self.lines) - 1))
        llen = len(self.lines[self.row])
        maxc = max(0, llen - (1 if self.mode == Mode.NORMAL and llen > 0 else 0))
        self.col = max(0, min(self.col, maxc))

    def _scroll(self, h, w, lw):
        cw = w - lw
        if self.row < self.top:
            self.top = self.row
        elif self.row >= self.top + h - 2:
            self.top = self.row - h + 3
        if self.col < self.left:
            self.left = self.col
        elif self.col >= self.left + cw - 1:
            self.left = self.col - cw + 2
        self.top  = max(0, self.top)
        self.left = max(0, self.left)

    # ── Search ────────────────────────────────────────────────────────────────
    def _search(self, pat: str):
        self.search_pat = pat
        self.matches = []
        if not pat:
            return
        try:
            rx = re.compile(pat)
        except re.error:
            rx = re.compile(re.escape(pat))
        for r, line in enumerate(self.lines):
            for m in rx.finditer(line):
                self.matches.append((r, m.start()))

    def _next_match(self, fwd=True):
        if not self.matches:
            self.msg = f"/{self.search_pat}: Not found"; return
        if fwd:
            for i, (r, c) in enumerate(self.matches):
                if (r, c) > (self.row, self.col):
                    self.match_idx = i
                    self.row, self.col = r, c
                    return
            self.match_idx = 0
        else:
            for i in range(len(self.matches) - 1, -1, -1):
                r, c = self.matches[i]
                if (r, c) < (self.row, self.col):
                    self.match_idx = i
                    self.row, self.col = r, c
                    return
            self.match_idx = len(self.matches) - 1
        self.row, self.col = self.matches[self.match_idx]

    # ── Autocomplete ──────────────────────────────────────────────────────────
    def _ac_prefix(self) -> str:
        line = self.lines[self.row]
        i = self.col - 1
        while i >= 0 and (line[i].isalpha() or line[i] in "*@"):
            i -= 1
        if i >= 0 and line[i] == "\\":
            return line[i:self.col]
        return ""

    def _ac_update(self):
        prefix = self._ac_prefix()
        if not prefix or prefix == "\\":
            self.ac_list = []; self.ac_idx = -1; self.ac_prefix = ""; return
        self.ac_prefix = prefix
        self.ac_list   = [c for c in LATEX_COMMANDS if c.startswith(prefix)][:12]
        if not self.ac_list:
            self.ac_idx = -1
        elif self.ac_idx >= len(self.ac_list):
            self.ac_idx = 0

    def _ac_apply(self):
        if self.ac_idx < 0 or not self.ac_list:
            return
        completion = self.ac_list[self.ac_idx]
        prefix     = self.ac_prefix
        line       = self.lines[self.row]
        start      = self.col - len(prefix)
        self.lines[self.row] = line[:start] + completion + line[self.col:]
        self.col   = start + len(completion)
        self.ac_list = []; self.ac_idx = -1; self.dirty = True

    # ── Movement helpers ──────────────────────────────────────────────────────
    def _word_fwd(self):
        line = self.lines[self.row]; col = self.col
        while col < len(line) and not line[col].isspace(): col += 1
        while col < len(line) and line[col].isspace():     col += 1
        if col >= len(line) and self.row < len(self.lines)-1:
            self.row += 1; self.col = 0
        else:
            self.col = col

    def _word_bwd(self):
        col = self.col
        if col == 0:
            if self.row > 0: self.row -= 1; self.col = len(self.lines[self.row])
            return
        line = self.lines[self.row]; col -= 1
        while col > 0 and line[col].isspace():     col -= 1
        while col > 0 and not line[col-1].isspace(): col -= 1
        self.col = col

    def _word_end(self):
        line = self.lines[self.row]; col = self.col + 1
        if col >= len(line):
            if self.row < len(self.lines)-1:
                self.row += 1; self.col = 0
            return
        while col < len(line)-1 and line[col].isspace():     col += 1
        while col < len(line)-1 and not line[col+1].isspace(): col += 1
        self.col = col

    # ── Drawing ───────────────────────────────────────────────────────────────
    def _draw(self, scr):
        scr.erase()
        h, w = scr.getmaxyx()
        lw   = len(str(len(self.lines))) + 2   # line number column width
        self._scroll(h, w, lw)

        ch   = h - 2                            # content rows
        cw   = w - lw                           # content cols

        segs_all = self._hl.get(self.lines)

        # Build search hit set
        hit_set = set(self.matches)

        # Visual range
        if self.mode == Mode.VISUAL:
            vr1 = min(self.vis_row, self.row)
            vr2 = max(self.vis_row, self.row)
        else:
            vr1 = vr2 = -1

        for sr in range(ch):
            br = self.top + sr
            if br >= len(self.lines):
                try: scr.addstr(sr, 0, "~", curses.color_pair(C_LINENO))
                except curses.error: pass
                continue

            # Line number
            lno = f"{br+1:>{lw-1}} "
            try: scr.addstr(sr, 0, lno, curses.color_pair(C_LINENO))
            except curses.error: pass

            line = self.lines[br]
            segs = segs_all[br] if br < len(segs_all) else [(line, C_DEFAULT)]

            x      = lw
            char_x = self.left

            for text, cp in segs:
                for ch_ch in text:
                    if char_x < self.left:
                        char_x += 1; continue
                    if x >= w - 1: break

                    attr = curses.color_pair(cp)

                    # Visual highlight
                    if vr1 <= br <= vr2:
                        attr = curses.color_pair(C_VISUAL) | curses.A_REVERSE

                    # Search highlight (overrides visual)
                    if (br, char_x) in hit_set:
                        attr = curses.color_pair(C_SEARCH) | curses.A_BOLD

                    try: scr.addstr(sr, x, ch_ch, attr)
                    except curses.error: pass
                    x += 1; char_x += 1

        # Status bar
        mstr = f" {self.mode.value} "
        fn   = self.filename or "[No Name]"
        fstr = f" {fn}{'*' if self.dirty else ''} "
        pstr = f" {self.row+1}:{self.col+1} "
        pad  = max(0, w - len(mstr) - len(fstr) - len(pstr))
        bar  = (mstr + fstr + " " * pad + pstr)[:w]
        try: scr.addstr(h-2, 0, bar, curses.color_pair(C_STATUS) | curses.A_BOLD)
        except curses.error: pass

        # Command / message line
        if self.mode == Mode.COMMAND:
            cl = (":" + self.cmd)[:w]
            try:
                scr.addstr(h-1, 0, cl)
                scr.move(h-1, min(len(cl), w-1))
            except curses.error: pass
        elif self.msg:
            try: scr.addstr(h-1, 0, self.msg[:w])
            except curses.error: pass

        # Autocomplete popup
        if self.ac_list and self.mode == Mode.INSERT:
            self._draw_ac(scr, h, w, lw)

        # Cursor
        if self.mode != Mode.COMMAND:
            sr = self.row - self.top
            sc = lw + self.col - self.left
            if 0 <= sr < h-2 and 0 <= sc < w:
                try: scr.move(sr, sc)
                except curses.error: pass

        scr.refresh()

    def _draw_ac(self, scr, h, w, lw):
        sr  = self.row - self.top
        sc  = lw + self.col - self.left - len(self.ac_prefix)
        n   = min(len(self.ac_list), 10)
        pw  = max((len(c) for c in self.ac_list[:n]), default=10) + 2
        pr  = sr + 1 if sr + 1 + n < h - 2 else sr - n
        pc  = max(0, min(sc, w - pw - 1))
        for i, item in enumerate(self.ac_list[:n]):
            text = f" {item:<{pw-1}}"[:pw]
            cp   = C_COMP_SEL if i == self.ac_idx else C_COMPLETE
            try: scr.addstr(pr + i, pc, text, curses.color_pair(cp))
            except curses.error: pass

    # ── Normal mode ───────────────────────────────────────────────────────────
    def _normal(self, key: int) -> bool:
        ch = chr(key) if 0 < key < 256 else ""

        # Digit accumulation
        if ch.isdigit() and (ch != "0" or self._cnt):
            self._cnt += ch; return True

        n = int(self._cnt) if self._cnt else 1
        self._cnt = ""

        # Pending two-key commands
        if self._pend:
            p, self._pend = self._pend, ""
            if p == "g":
                if ch == "g": self.row = 0; self.col = 0
            elif p == "d":
                if ch == "d":
                    self._push()
                    for _ in range(n):
                        if len(self.lines) > 1:
                            del self.lines[self.row]
                            self.row = min(self.row, len(self.lines)-1)
                        else:
                            self.lines[0] = ""
                    self.dirty = True; self._clamp()
            elif p == "y":
                if ch == "y":
                    self.reg = "\n".join(self.lines[self.row:self.row+n])
                    self.reg_lines = True
                    self.msg = f"Yanked {n} line(s)"
            return True

        # ── Movement
        if   key == curses.KEY_UP   or ch == "k": self.row = max(0, self.row - n); self._clamp()
        elif key == curses.KEY_DOWN  or ch == "j": self.row = min(len(self.lines)-1, self.row+n); self._clamp()
        elif key == curses.KEY_LEFT  or ch == "h": self.col = max(0, self.col - n)
        elif key == curses.KEY_RIGHT or ch == "l":
            self.col = min(max(0, len(self.lines[self.row])-1), self.col + n)
        elif key == curses.KEY_HOME  or ch == "0": self.col = 0
        elif key == curses.KEY_END   or ch == "$": self.col = max(0, len(self.lines[self.row])-1)
        elif ch == "^":
            ln = self.lines[self.row]; self.col = len(ln) - len(ln.lstrip())
        elif ch == "w": [self._word_fwd() for _ in range(n)]
        elif ch == "b": [self._word_bwd() for _ in range(n)]
        elif ch == "e": [self._word_end() for _ in range(n)]
        elif ch == "G": self.row = len(self.lines)-1; self.col = 0
        elif ch == "g": self._pend = "g"
        elif key == curses.KEY_PPAGE or key == 339: self.row = max(0, self.row-20); self._clamp()
        elif key == curses.KEY_NPAGE or key == 338: self.row = min(len(self.lines)-1, self.row+20); self._clamp()
        elif key == 4:  self.row = min(len(self.lines)-1, self.row+10); self._clamp()   # Ctrl+D
        elif key == 21: self.row = max(0, self.row-10); self._clamp()                   # Ctrl+U

        # ── Enter insert
        elif ch == "i": self._push(); self.mode = Mode.INSERT
        elif ch == "I":
            self._push(); self.mode = Mode.INSERT
            self.col = len(self.lines[self.row]) - len(self.lines[self.row].lstrip())
        elif ch == "a":
            self._push(); self.mode = Mode.INSERT
            if self.lines[self.row]: self.col = min(self.col+1, len(self.lines[self.row]))
        elif ch == "A":
            self._push(); self.mode = Mode.INSERT; self.col = len(self.lines[self.row])
        elif ch == "o":
            self._push()
            self.row += 1
            # Auto-indent based on current line
            indent = len(self.lines[self.row-1]) - len(self.lines[self.row-1].lstrip())
            self.lines.insert(self.row, " " * indent)
            self.col = indent; self.mode = Mode.INSERT; self.dirty = True
        elif ch == "O":
            self._push()
            indent = len(self.lines[self.row]) - len(self.lines[self.row].lstrip())
            self.lines.insert(self.row, " " * indent)
            self.col = indent; self.mode = Mode.INSERT; self.dirty = True

        # ── Edit
        elif ch == "x":
            self._push(); line = self.lines[self.row]
            if self.col < len(line):
                self.lines[self.row] = line[:self.col] + line[self.col+1:]
                self.dirty = True; self._clamp()
        elif ch == "D":
            self._push(); self.lines[self.row] = self.lines[self.row][:self.col]; self.dirty = True
        elif ch == "d": self._pend = "d"
        elif ch == "J":
            self._push()
            if self.row < len(self.lines)-1:
                self.lines[self.row] = self.lines[self.row].rstrip() + " " + self.lines[self.row+1].lstrip()
                del self.lines[self.row+1]; self.dirty = True

        # ── Yank / paste
        elif ch == "y": self._pend = "y"
        elif ch == "Y":
            self.reg = self.lines[self.row]; self.reg_lines = True; self.msg = "Yanked line"
        elif ch == "p":
            self._push()
            if self.reg_lines:
                self.lines.insert(self.row+1, self.reg); self.row += 1
            else:
                ln = self.lines[self.row]
                self.lines[self.row] = ln[:self.col+1] + self.reg + ln[self.col+1:]
                self.col += len(self.reg)
            self.dirty = True
        elif ch == "P":
            self._push()
            if self.reg_lines:
                self.lines.insert(self.row, self.reg)
            else:
                ln = self.lines[self.row]
                self.lines[self.row] = ln[:self.col] + self.reg + ln[self.col:]
            self.dirty = True

        # ── Undo / Redo
        elif ch == "u": self._undo()
        elif key == 18: self._redo()           # Ctrl+R

        # ── Search
        elif ch == "/":
            self.mode = Mode.COMMAND; self.cmd = "/"
        elif ch == "n": self._next_match(True)
        elif ch == "N": self._next_match(False)

        # ── Command / visual
        elif ch == ":": self.mode = Mode.COMMAND; self.cmd = ""
        elif ch == "v":
            self.mode = Mode.VISUAL; self.vis_row = self.row; self.vis_col = self.col

        return True

    # ── Insert mode ───────────────────────────────────────────────────────────
    def _insert(self, key: int) -> bool:
        ch = chr(key) if 0 < key < 256 else ""

        # ESC → Normal
        if key == 27:
            self.mode = Mode.NORMAL
            self.col  = max(0, self.col - 1)
            self.ac_list = []; self.ac_idx = -1
            return True

        # Autocomplete navigation
        if self.ac_list:
            if key == 9 or key == curses.KEY_DOWN:
                self.ac_idx = (self.ac_idx + 1) % len(self.ac_list); return True
            if key == curses.KEY_UP:
                self.ac_idx = (self.ac_idx - 1) % len(self.ac_list); return True
            if key in (10, 13) and self.ac_idx >= 0:
                self._ac_apply(); return True
            if key == 27:
                self.ac_list = []; self.ac_idx = -1; return True

        # Tab
        if key == 9:
            prefix = self._ac_prefix()
            if prefix:
                self._ac_update()
                if self.ac_list: self.ac_idx = 0
            else:
                line = self.lines[self.row]
                self.lines[self.row] = line[:self.col] + "    " + line[self.col:]
                self.col += 4; self.dirty = True
            return True

        # Backspace
        if key in (8, 127, curses.KEY_BACKSPACE):
            line = self.lines[self.row]
            if self.col > 0:
                # Auto-pair: delete both if we're between a pair
                if self.col < len(line) and \
                   line[self.col-1] + line[self.col] in ("{}", "[]", "()", "$$"):
                    self.lines[self.row] = line[:self.col-1] + line[self.col+1:]
                else:
                    self.lines[self.row] = line[:self.col-1] + line[self.col:]
                self.col -= 1
            elif self.row > 0:
                prev = self.lines[self.row-1]
                self.col = len(prev)
                self.lines[self.row-1] = prev + line
                del self.lines[self.row]; self.row -= 1
            self.dirty = True; self._ac_update(); return True

        # Delete
        if key == curses.KEY_DC:
            line = self.lines[self.row]
            if self.col < len(line):
                self.lines[self.row] = line[:self.col] + line[self.col+1:]
            elif self.row < len(self.lines)-1:
                self.lines[self.row] = line + self.lines[self.row+1]
                del self.lines[self.row+1]
            self.dirty = True; return True

        # Enter
        if key in (10, 13):
            line   = self.lines[self.row]
            before = line[:self.col]
            after  = line[self.col:]
            indent = len(before) - len(before.lstrip())
            # Extra indent after \begin or opening brace
            stripped = before.rstrip()
            if stripped.endswith("{") or re.search(r'\\begin\{[^}]*\}$', stripped):
                indent += 4
            new_line = " " * indent + after
            self.lines[self.row] = before
            self.row += 1
            self.lines.insert(self.row, new_line)
            self.col = indent; self.dirty = True
            self.ac_list = []; return True

        # Arrow keys
        if key == curses.KEY_UP:    self.row = max(0, self.row-1); self._clamp(); return True
        if key == curses.KEY_DOWN:  self.row = min(len(self.lines)-1, self.row+1); self._clamp(); return True
        if key == curses.KEY_LEFT:  self.col = max(0, self.col-1); return True
        if key == curses.KEY_RIGHT: self.col = min(len(self.lines[self.row]), self.col+1); return True
        if key == curses.KEY_HOME:  self.col = 0; return True
        if key == curses.KEY_END:   self.col = len(self.lines[self.row]); return True

        # Printable character
        if 32 <= key < 256:
            line = self.lines[self.row]
            self.lines[self.row] = line[:self.col] + ch + line[self.col:]
            self.col += 1; self.dirty = True

            # Auto-pair
            pairs = {"{": "}", "[": "]", "(": ")", "$": "$"}
            if ch in pairs:
                ln = self.lines[self.row]
                self.lines[self.row] = ln[:self.col] + pairs[ch] + ln[self.col:]

            self._ac_update()

        return True

    # ── Command mode ──────────────────────────────────────────────────────────
    def _command(self, key: int) -> bool:
        if key == 27:
            self.mode = Mode.NORMAL; self.cmd = ""; return True

        if key in (10, 13):
            return self._exec()

        if key in (8, 127, curses.KEY_BACKSPACE):
            if self.cmd:
                self.cmd = self.cmd[:-1]
                # Live search preview
                if self.cmd.startswith("/") and len(self.cmd) > 1:
                    self._search(self.cmd[1:])
            else:
                self.mode = Mode.NORMAL
            return True

        if 32 <= key < 256:
            self.cmd += chr(key)
            if self.cmd.startswith("/") and len(self.cmd) > 1:
                self._search(self.cmd[1:])
            return True

        return True

    def _exec(self) -> bool:
        raw = self.cmd
        self.cmd = ""; self.mode = Mode.NORMAL

        # Search
        if raw.startswith("/"):
            pat = raw[1:]
            self._search(pat)
            self._next_match(True)
            return True

        parts = raw.strip().split(None, 1)
        c0    = parts[0] if parts else ""

        if c0 == "q":
            if self.dirty:
                self.msg = "Unsaved changes — use :wq to save or :q! to discard"
                return True
            return False
        elif c0 == "q!":
            return False
        elif c0 == "w":
            if len(parts) > 1: self.filename = parts[1].strip()
            self._save()
        elif c0 in ("wq", "x"):
            if len(parts) > 1: self.filename = parts[1].strip()
            if self._save():
                ok = self._compile()
                if ok:
                    self._open_pdf()
                    return False
                # Stay if compile failed so user can fix errors
            return True
        elif c0 == "pdf":
            self._save(); self._compile()
        elif c0 == "e":
            if len(parts) > 1:
                self.filename = parts[1].strip()
                self._load(); self.row = self.col = self.top = self.left = 0
            else:
                self.msg = "Usage: :e <filename>"
        else:
            self.msg = f"Unknown command: {c0}"

        return True

    # ── Visual mode ───────────────────────────────────────────────────────────
    def _visual(self, key: int) -> bool:
        ch = chr(key) if 0 < key < 256 else ""

        if key == 27 or ch == "v": self.mode = Mode.NORMAL; return True

        if key == curses.KEY_UP   or ch == "k": self.row = max(0, self.row-1)
        elif key == curses.KEY_DOWN or ch == "j": self.row = min(len(self.lines)-1, self.row+1)
        elif key == curses.KEY_LEFT  or ch == "h": self.col = max(0, self.col-1)
        elif key == curses.KEY_RIGHT or ch == "l":
            self.col = min(max(0, len(self.lines[self.row])-1), self.col+1)
        elif ch == "0": self.col = 0
        elif ch == "$": self.col = max(0, len(self.lines[self.row])-1)
        elif ch == "G": self.row = len(self.lines)-1
        elif ch == "w": self._word_fwd()
        elif ch == "b": self._word_bwd()
        elif ch in ("d", "x"):
            self._push()
            r1 = min(self.vis_row, self.row)
            r2 = max(self.vis_row, self.row)
            self.reg = "\n".join(self.lines[r1:r2+1]); self.reg_lines = True
            del self.lines[r1:r2+1]
            if not self.lines: self.lines = [""]
            self.row = r1; self._clamp(); self.dirty = True; self.mode = Mode.NORMAL
        elif ch == "y":
            r1 = min(self.vis_row, self.row)
            r2 = max(self.vis_row, self.row)
            self.reg = "\n".join(self.lines[r1:r2+1]); self.reg_lines = True
            self.msg = f"Yanked {r2-r1+1} line(s)"; self.mode = Mode.NORMAL

        return True

    # ── Main loop ─────────────────────────────────────────────────────────────
    def _main(self, scr):
        _init_colors()
        curses.curs_set(1)
        scr.keypad(True)

        while True:
            self._draw(scr)
            try:
                key = scr.get_wch()
            except curses.error:
                continue

            # Normalize key
            if isinstance(key, str):
                key = ord(key)

            self.msg = ""   # clear old message on any keypress

            if   self.mode == Mode.NORMAL:  cont = self._normal(key)
            elif self.mode == Mode.INSERT:  cont = self._insert(key)
            elif self.mode == Mode.COMMAND: cont = self._command(key)
            elif self.mode == Mode.VISUAL:  cont = self._visual(key)
            else: cont = True

            if not cont:
                break

    def run(self):
        curses.wrapper(self._main)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("LaTeX Vim Editor")
        print("Usage: python editor.py <file.tex>")
        print()
        print("Starting with empty buffer. Use :w <filename> to save.")
        filename = None
    else:
        filename = sys.argv[1]

    Editor(filename).run()

if __name__ == "__main__":
    main()
