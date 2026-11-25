"""
Counts the words in main.tex per section against the guide's budgets.

Counted: running text in each section, including captions and the text inside tables.
Not counted: LaTeX commands, citation keys, equations, algorithm pseudocode, the bibliography, the AI-use
declaration and the contribution statements (they come after the Conclusion and are not part of the paper body).

    python count_words.py
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
BUDGET = {  # section: (low, high); the guide allows +-10 percent
    "Abstract": (200, 250),
    "Introduction": (600, 800),
    "Related Work": (700, 900),
    "Background and Problem Formulation": (300, 500),
    "Proposed Methodology": (900, 1200),
    "Experimental Setup": (400, 600),
    "Results and Analysis": (800, 1000),
    "Discussion": (300, 500),
    "Conclusion and Future Work": (200, 300),
}


def clean(text, keep_tables):
    text = re.sub(r"(?<!\\)%.*", "", text)
    text = re.sub(r"\\begin\{(equation|algorithm)\*?\}.*?\\end\{\1\*?\}", " ", text, flags=re.S)
    text = re.sub(r"\$[^$]*\$", " x ", text)
    if not keep_tables:
        text = re.sub(r"\\begin\{(table|figure)\*?\}.*?\\end\{\1\*?\}", " ", text, flags=re.S)
    text = re.sub(r"\\(cite|ref|label|url|includegraphics)(\[[^\]]*\])?\{[^}]*\}", " ", text)
    text = re.sub(r"\\begin\{tabular\}\{[^}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", text)
    text = re.sub(r"[{}\\&]|--+", " ", text)
    return text


def words(text):
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'.,%/+-]*", text))


def main():
    tex = open(os.path.join(HERE, "main.tex"), encoding="utf-8").read()
    abstract = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", tex, re.S).group(1)
    body = tex.split("\\section{Introduction}", 1)[1]
    body = re.split(r"\\section\*\{AI-use declaration\}", body)[0]
    parts = re.split(r"\\section\{([^}]*)\}", "\\section{Introduction}" + body)
    counts = {"Abstract": (words(clean(abstract, True)), words(clean(abstract, True)))}
    for i in range(1, len(parts), 2):
        name, text = parts[i], parts[i + 1]
        counts[name] = (words(clean(text, False)), words(clean(text, True)))

    total_text = total_all = 0
    print(f"{'section':<38}{'text only':>10}{'with tables':>13}   budget (+-10%)")
    for name, (lo, hi) in BUDGET.items():
        text_only, with_tables = counts.get(name, (0, 0))
        total_text += text_only
        total_all += with_tables
        ok = int(lo * 0.9) <= with_tables <= int(hi * 1.1)
        print(f"{name:<38}{text_only:>10}{with_tables:>13}   {lo}-{hi}  {'ok' if ok else 'CHECK'}")
    print(f"{'TOTAL':<38}{total_text:>10}{total_all:>13}   4500-5500")
    cited = set()
    for m in re.findall(r"\\cite\{([^}]*)\}", tex):
        cited |= {k.strip() for k in m.split(",")}
    print("distinct references cited:", len(cited), "(guide: 15-25)")


if __name__ == "__main__":
    main()
