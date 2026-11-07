import json, io, sys
cells = []
def _lines(s):
    """nbformat menyimpan source sebagai daftar baris yang MASIH berakhiran \n.

    Tanpa \n, seluruh sel menyatu jadi satu baris saat dieksekusi.
    """
    out = s.strip("\n").split("\n")
    return [ln + "\n" for ln in out[:-1]] + [out[-1]]

_n = [0]
def _cell(kind, s, extra=None):
    _n[0] += 1
    c = {"cell_type": kind, "metadata": {}, "id": f"c{_n[0]:03d}",
         "source": _lines(s)}
    if extra: c.update(extra)
    cells.append(c)

def md(s): _cell("markdown", s)
def code(s): _cell("code", s, {"execution_count": None, "outputs": []})
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(_HERE, "nb_cells.py"), encoding="utf-8").read())
nb = {"cells":cells,
      "metadata":{"kernelspec":{"display_name":"Python 3","language":"python","name":"python3"},
                  "language_info":{"name":"python","version":"3"}},
      "nbformat":4,"nbformat_minor":5}
_out = os.path.join(_HERE, "eda_people_count.ipynb")
json.dump(nb, open(_out,"w",encoding="utf-8"), indent=1, ensure_ascii=False)
print("cells:", len(cells))
