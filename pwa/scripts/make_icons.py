import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Polygon

OUT = r"d:\Projects\Sceptic\frontend\public\icons"
os.makedirs(OUT, exist_ok=True)
BG, ACCENT = "#0c0d0f", "#8fb0ff"


def draw(size, name, maskable=False, rounded=True):
    fig = plt.figure(figsize=(size / 100, size / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    fig.patch.set_alpha(0)
    if maskable:
        ax.add_patch(plt.Rectangle((0, 0), 100, 100, fc=BG, ec="none"))
        scale = 0.62      # keep the mark inside the 80% safe zone
    elif rounded:
        ax.add_patch(FancyBboxPatch((0, 0), 100, 100, boxstyle="round,pad=0,rounding_size=22", fc=BG, ec="none"))
        scale = 0.74
    else:
        ax.add_patch(plt.Rectangle((0, 0), 100, 100, fc=BG, ec="none"))
        scale = 0.74
    cx, cy = 50, 50

    def p(x, y):
        return (cx + (x - 50) * scale, cy + (y - 50) * scale)

    shield = [(50, 92), (86, 80), (86, 50), (78, 30), (50, 8), (22, 30), (14, 50), (14, 80)]
    ax.add_patch(Polygon([p(*pt) for pt in shield], closed=True, fc="none", ec=ACCENT, lw=size * 0.045, joinstyle="round"))
    check = [(33, 50), (46, 38), (68, 64)]
    xs, ys = zip(*[p(*pt) for pt in check])
    ax.plot(xs, ys, color=ACCENT, lw=size * 0.06, solid_capstyle="round", solid_joinstyle="round")
    fig.savefig(os.path.join(OUT, name), dpi=100, transparent=True)
    plt.close(fig)
    print("wrote", name)


draw(192, "icon-192.png")
draw(512, "icon-512.png")
draw(512, "maskable-512.png", maskable=True)
draw(180, "apple-touch-icon.png", rounded=False)
