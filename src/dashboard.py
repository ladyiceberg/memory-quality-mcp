"""
dashboard.py · Memory Health Dashboard HTML 生成器

从 session_store 读取最近一次 report 结果，生成一个完整的 HTML 文件，
用系统默认浏览器打开，呈现苹果极简风格的记忆健康报告。

设计原则：
  - 苹果 Light 调性：systemGray6 背景、白色卡片、SF Pro 字体栈
  - Summary First：进入页面先看健康分圆环和核心数字，细节折叠展开
  - 纯 HTML + CSS + 内联 JS，零外部依赖，本地文件即可运行
  - 所有颜色来自苹果官方 HIG 系统色（2024）
"""

import time
import webbrowser
from pathlib import Path
from typing import Optional

from src.session_store import StoredReport, ReportEntry


# ── 苹果官方系统色（Light Mode，来自 Apple HIG 2024）─────────────────────────

COLORS = {
    # 背景层级
    "bg_page":       "#F2F2F7",   # systemGray6 - 页面底色
    "bg_card":       "#FFFFFF",   # systemBackground - 卡片白
    "bg_secondary":  "#F2F2F7",   # systemGray6 - 卡片内次级区域
    "bg_tertiary":   "#E5E5EA",   # systemGray5 - 深一级的分隔

    # 文字层级（苹果网站实测值）
    "text_primary":   "#1D1D1F",  # 苹果标准正文黑
    "text_secondary": "#6E6E73",  # 副文字灰（苹果网站用）
    "text_tertiary":  "#AEAEB2",  # systemGray2 - 时间戳/次要信息
    "text_link":      "#0066CC",  # 苹果链接蓝

    # 边框
    "border":         "rgba(0,0,0,0.08)",
    "divider":        "rgba(0,0,0,0.05)",

    # 状态色（苹果官方系统色）
    "green":   "#34C759",  # systemGreen - 保留/健康
    "orange":  "#FF9500",  # systemOrange - 复查/警告
    "red":     "#FF3B30",  # systemRed - 删除/危险
    "blue":    "#007AFF",  # systemBlue - 强调/操作
    "indigo":  "#5856D6",  # systemIndigo - 健康分圆环主色

    # 状态背景（浅色版，8% 透明度）
    "green_bg":  "rgba(52,199,89,0.08)",
    "orange_bg": "rgba(255,149,0,0.08)",
    "red_bg":    "rgba(255,59,48,0.08)",
    "indigo_bg": "rgba(88,86,214,0.08)",
}


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _compute_health_score(entries: list[ReportEntry]) -> int:
    """
    从评分结果计算 0-100 的综合健康分。
    逻辑：保留比例越高分越高，同时考虑平均综合分。
    """
    if not entries:
        return 100

    total = len(entries)
    keep_count = sum(1 for e in entries if e.action == "keep")
    review_count = sum(1 for e in entries if e.action == "review")
    delete_count = sum(1 for e in entries if e.action == "delete")

    # 基础分：保留比例
    keep_ratio = keep_count / total
    review_ratio = review_count / total

    # 综合健康分 = 保留×100 + 复查×50 + 删除×0，再除以总数
    weighted = (keep_count * 100 + review_count * 50 + delete_count * 0) / total

    # 平均四维分（0-5 → 0-100）
    valid_scores = [e.composite for e in entries if e.composite > 0]
    avg_score = (sum(valid_scores) / len(valid_scores) * 20) if valid_scores else 60

    # 最终分 = 权重平均
    health = int(weighted * 0.6 + avg_score * 0.4)
    return max(0, min(100, health))


def _score_color(score: float) -> str:
    """根据综合分返回对应颜色。"""
    if score >= 3.5:
        return COLORS["green"]
    if score >= 2.5:
        return COLORS["orange"]
    return COLORS["red"]


def _health_color(health: int) -> str:
    """根据健康分返回圆环颜色。"""
    if health >= 80:
        return COLORS["green"]
    if health >= 60:
        return COLORS["orange"]
    return COLORS["red"]


def _action_icon(action: str) -> str:
    return {"keep": "✓", "review": "!", "delete": "×"}.get(action, "?")


def _action_label(action: str) -> str:
    return {"keep": "保留", "review": "复查", "delete": "删除"}.get(action, action)


def _action_color(action: str) -> str:
    return {
        "keep": COLORS["green"],
        "review": COLORS["orange"],
        "delete": COLORS["red"],
    }.get(action, COLORS["text_secondary"])


def _action_bg(action: str) -> str:
    return {
        "keep": COLORS["green_bg"],
        "review": COLORS["orange_bg"],
        "delete": COLORS["red_bg"],
    }.get(action, "transparent")


def _dim_bar(score: float, max_score: float = 5.0) -> str:
    """生成四维评分的横向进度条 HTML。"""
    pct = int(score / max_score * 100)
    color = _score_color(score)
    return f"""<div class="dim-bar-track">
        <div class="dim-bar-fill" style="width:{pct}%;background:{color}"></div>
    </div>"""


def _age_display(age_days: int) -> str:
    if age_days == 0:
        return "今天"
    if age_days == 1:
        return "昨天"
    if age_days < 30:
        return f"{age_days} 天前"
    if age_days < 365:
        return f"{age_days // 30} 个月前"
    return f"{age_days // 365} 年前"


def _memory_type_label(t: Optional[str]) -> str:
    return {
        "user": "用户偏好",
        "feedback": "行为反馈",
        "project": "项目背景",
        "reference": "外部引用",
    }.get(t or "", t or "未知")


# ── SVG 圆环组件 ───────────────────────────────────────────────────────────────

def _ring_svg(health: int) -> str:
    """
    生成健康分圆环 SVG。
    用 stroke-dasharray 控制圆弧长度，纯 SVG 无库依赖。
    """
    radius = 54
    circumference = 2 * 3.14159 * radius  # ≈ 339.3
    progress = health / 100 * circumference
    gap = circumference - progress
    color = _health_color(health)

    # 健康分文字颜色
    score_color = color

    return f"""<svg class="ring-svg" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- 背景轨道 -->
  <circle cx="60" cy="60" r="{radius}" stroke="{COLORS['bg_tertiary']}" stroke-width="8"/>
  <!-- 进度弧（从12点方向开始，顺时针）-->
  <circle
    cx="60" cy="60" r="{radius}"
    stroke="{color}"
    stroke-width="8"
    stroke-linecap="round"
    stroke-dasharray="{progress:.1f} {gap:.1f}"
    transform="rotate(-90 60 60)"
    style="transition: stroke-dasharray 0.8s ease"
  />
  <!-- 中心数字 -->
  <text x="60" y="56" text-anchor="middle" dominant-baseline="middle"
    font-family="-apple-system, SF Pro Display, Helvetica Neue, sans-serif"
    font-size="26" font-weight="700" fill="{score_color}">{health}</text>
  <text x="60" y="74" text-anchor="middle" dominant-baseline="middle"
    font-family="-apple-system, SF Pro Text, Helvetica Neue, sans-serif"
    font-size="10" font-weight="400" fill="{COLORS['text_tertiary']}" letter-spacing="0.5">/ 100</text>
</svg>"""


# ── 主 HTML 生成 ──────────────────────────────────────────────────────────────

def generate_dashboard_html(report: StoredReport) -> str:
    """生成完整的 Dashboard HTML 字符串。"""

    entries = report.entries
    health = _compute_health_score(entries)
    health_color = _health_color(health)

    keep_entries   = [e for e in entries if e.action == "keep"]
    review_entries = [e for e in entries if e.action == "review"]
    delete_entries = [e for e in entries if e.action == "delete"]

    # 冲突对（从 delete/review 里找有冲突标记的，目前 session_store 未存冲突信息，留空）
    # 未来可扩展
    conflict_pairs: list[tuple[str, str]] = []

    age_str = report.age_display()
    scan_time = time.strftime("%Y年%m月%d日 %H:%M", time.localtime(report.created_at))
    total = len(entries)

    ring = _ring_svg(health)

    # ── 四维平均分 ────────────────────────────────────────────────────────────
    def _avg_dim(dim: str) -> float:
        vals = [getattr(e, dim, 0) for e in entries
                if getattr(e, dim, 0) and getattr(e, dim, 0) > 0]
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    # session_store 只存了 composite，需要从记忆内容反推——
    # 此版本用 composite 近似显示，完整四维在 report 完成后可从 engine 结果存入
    avg_composite = _avg_dim("composite")

    # ── 记忆条目 HTML ─────────────────────────────────────────────────────────
    def _entry_card(e: ReportEntry, index: int) -> str:
        color = _action_color(e.action)
        bg = _action_bg(e.action)
        icon = _action_icon(e.action)
        label = _action_label(e.action)
        age = _age_display(e.age_days if hasattr(e, 'age_days') else 0)
        type_label = _memory_type_label(e.memory_type)
        score_pct = int(e.composite / 5 * 100)
        filename_short = Path(e.filename).stem.replace("_", " ")

        return f"""
<div class="entry-card" onclick="toggleEntry(this)" data-index="{index}">
  <div class="entry-header">
    <div class="entry-left">
      <span class="entry-badge" style="color:{color};background:{bg}">{icon} {label}</span>
      <span class="entry-name">{filename_short}</span>
    </div>
    <div class="entry-right">
      <span class="entry-meta">{type_label}</span>
      <span class="entry-meta muted">{age}</span>
      <span class="entry-score" style="color:{color}">{e.composite:.1f}</span>
      <svg class="chevron" width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M3 4.5L6 7.5L9 4.5" stroke="{COLORS['text_tertiary']}" stroke-width="1.5" stroke-linecap="round"/>
      </svg>
    </div>
  </div>
  <div class="entry-detail">
    <div class="entry-score-bar">
      <div class="score-bar-fill" style="width:{score_pct}%;background:{color}"></div>
    </div>
    <p class="entry-reason">{e.reason}</p>
    <p class="entry-filename">{e.filename}</p>
  </div>
</div>"""

    def _section(title: str, action: str, items: list[ReportEntry], default_open: bool = False) -> str:
        if not items:
            return ""
        color = _action_color(action)
        icon = _action_icon(action)
        open_attr = "open" if default_open else ""
        cards = "\n".join(_entry_card(e, i) for i, e in enumerate(items))
        return f"""
<details class="section-details" {open_attr}>
  <summary class="section-summary">
    <div class="section-title-row">
      <span class="section-icon" style="color:{color}">{icon}</span>
      <span class="section-title">{title}</span>
      <span class="section-count" style="color:{color}">{len(items)}</span>
    </div>
    <svg class="section-chevron" width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M3.5 5.25L7 8.75L10.5 5.25" stroke="{COLORS['text_secondary']}" stroke-width="1.5" stroke-linecap="round"/>
    </svg>
  </summary>
  <div class="section-body">
    {cards}
  </div>
</details>"""

    delete_section = _section("建议删除", "delete", delete_entries, default_open=True)
    review_section = _section("建议复查", "review", review_entries, default_open=True)
    keep_section   = _section("状态良好", "keep", keep_entries,   default_open=False)

    # ── 健康状态语 ────────────────────────────────────────────────────────────
    if health >= 80:
        health_headline = "记忆库状态良好"
        health_sub = "大部分记忆质量高，可以放心使用。"
    elif health >= 60:
        health_headline = "记忆库需要关注"
        health_sub = f"有 {len(review_entries) + len(delete_entries)} 条记忆建议处理。"
    else:
        health_headline = "记忆库需要清理"
        health_sub = f"有 {len(delete_entries)} 条建议删除，{len(review_entries)} 条需要复查。"

    # ── 完整 HTML ─────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Memory Health · {scan_time}</title>
<style>

/* ── Reset & Base ─────────────────────────────────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: -apple-system, "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
  background: {COLORS['bg_page']};
  color: {COLORS['text_primary']};
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}

/* ── Layout ───────────────────────────────────────────────────────────── */
.page {{
  max-width: 680px;
  margin: 0 auto;
  padding: 48px 20px 80px;
}}

/* ── Header ───────────────────────────────────────────────────────────── */
.header {{
  margin-bottom: 32px;
}}
.header-top {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}}
.header-title {{
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.3px;
  color: {COLORS['text_primary']};
}}
.header-badge {{
  font-size: 11px;
  font-weight: 500;
  color: {COLORS['text_tertiary']};
  background: {COLORS['bg_card']};
  border: 1px solid {COLORS['border']};
  border-radius: 20px;
  padding: 3px 10px;
  letter-spacing: 0.2px;
}}
.header-sub {{
  font-size: 13px;
  color: {COLORS['text_tertiary']};
}}

/* ── Hero Card ────────────────────────────────────────────────────────── */
.hero-card {{
  background: {COLORS['bg_card']};
  border-radius: 16px;
  box-shadow: 0 1px 0 {COLORS['border']}, 0 4px 20px rgba(0,0,0,0.05);
  padding: 32px 28px 28px;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 32px;
}}
.ring-svg {{
  width: 120px;
  height: 120px;
  flex-shrink: 0;
}}
.hero-right {{
  flex: 1;
  min-width: 0;
}}
.hero-headline {{
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.3px;
  color: {COLORS['text_primary']};
  margin-bottom: 4px;
}}
.hero-sub {{
  font-size: 14px;
  color: {COLORS['text_secondary']};
  margin-bottom: 20px;
  line-height: 1.4;
}}
.stats-row {{
  display: flex;
  gap: 0;
  border: 1px solid {COLORS['border']};
  border-radius: 10px;
  overflow: hidden;
}}
.stat-item {{
  flex: 1;
  padding: 10px 0;
  text-align: center;
  border-right: 1px solid {COLORS['border']};
}}
.stat-item:last-child {{ border-right: none; }}
.stat-number {{
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.5px;
  line-height: 1;
  margin-bottom: 3px;
}}
.stat-label {{
  font-size: 11px;
  color: {COLORS['text_tertiary']};
  letter-spacing: 0.2px;
}}

/* ── Dim Cards (四维评分) ─────────────────────────────────────────────── */
.dim-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 12px;
}}
.dim-card {{
  background: {COLORS['bg_card']};
  border-radius: 12px;
  box-shadow: 0 1px 0 {COLORS['border']}, 0 2px 8px rgba(0,0,0,0.04);
  padding: 16px 16px 14px;
}}
.dim-name {{
  font-size: 12px;
  color: {COLORS['text_tertiary']};
  margin-bottom: 6px;
  letter-spacing: 0.2px;
}}
.dim-score {{
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.5px;
  line-height: 1;
  margin-bottom: 8px;
}}
.dim-bar-track {{
  height: 3px;
  background: {COLORS['bg_tertiary']};
  border-radius: 2px;
  overflow: hidden;
}}
.dim-bar-fill {{
  height: 100%;
  border-radius: 2px;
  transition: width 0.6s ease;
}}

/* ── Section ──────────────────────────────────────────────────────────── */
.section-details {{
  background: {COLORS['bg_card']};
  border-radius: 12px;
  box-shadow: 0 1px 0 {COLORS['border']}, 0 2px 8px rgba(0,0,0,0.04);
  margin-bottom: 10px;
  overflow: hidden;
}}
.section-summary {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px;
  cursor: pointer;
  user-select: none;
  list-style: none;
  transition: background 0.15s;
}}
.section-summary:hover {{ background: {COLORS['bg_page']}; }}
.section-summary::-webkit-details-marker {{ display: none; }}
.section-title-row {{
  display: flex;
  align-items: center;
  gap: 8px;
}}
.section-icon {{
  font-size: 15px;
  width: 20px;
  text-align: center;
}}
.section-title {{
  font-size: 15px;
  font-weight: 600;
  color: {COLORS['text_primary']};
}}
.section-count {{
  font-size: 13px;
  font-weight: 600;
  background: currentColor;
  -webkit-background-clip: text;
  opacity: 0.85;
}}
.section-chevron {{
  transition: transform 0.2s ease;
  flex-shrink: 0;
}}
details[open] .section-chevron {{
  transform: rotate(180deg);
}}
.section-body {{
  border-top: 1px solid {COLORS['divider']};
  padding: 8px 10px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}}

/* ── Entry Card ───────────────────────────────────────────────────────── */
.entry-card {{
  border-radius: 8px;
  padding: 12px 14px;
  cursor: pointer;
  transition: background 0.15s;
}}
.entry-card:hover {{ background: {COLORS['bg_page']}; }}
.entry-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}}
.entry-left {{
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}}
.entry-badge {{
  font-size: 11px;
  font-weight: 600;
  border-radius: 5px;
  padding: 2px 7px;
  white-space: nowrap;
  flex-shrink: 0;
  letter-spacing: 0.1px;
}}
.entry-name {{
  font-size: 14px;
  font-weight: 500;
  color: {COLORS['text_primary']};
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.entry-right {{
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}}
.entry-meta {{
  font-size: 12px;
  color: {COLORS['text_secondary']};
  white-space: nowrap;
}}
.entry-meta.muted {{ color: {COLORS['text_tertiary']}; }}
.entry-score {{
  font-size: 13px;
  font-weight: 600;
  min-width: 24px;
  text-align: right;
}}
.chevron {{
  transition: transform 0.2s ease;
  flex-shrink: 0;
}}
.entry-card.expanded .chevron {{
  transform: rotate(180deg);
}}

/* ── Entry Detail（展开内容）────────────────────────────────────────────── */
.entry-detail {{
  display: none;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid {COLORS['divider']};
}}
.entry-card.expanded .entry-detail {{
  display: block;
}}
.entry-score-bar {{
  height: 3px;
  background: {COLORS['bg_tertiary']};
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 10px;
}}
.score-bar-fill {{
  height: 100%;
  border-radius: 2px;
  transition: width 0.5s ease;
}}
.entry-reason {{
  font-size: 13px;
  color: {COLORS['text_secondary']};
  line-height: 1.5;
  margin-bottom: 6px;
}}
.entry-filename {{
  font-size: 11px;
  color: {COLORS['text_tertiary']};
  font-family: "SF Mono", "Menlo", monospace;
  background: {COLORS['bg_secondary']};
  border-radius: 4px;
  padding: 3px 7px;
  display: inline-block;
}}

/* ── Footer ───────────────────────────────────────────────────────────── */
.footer {{
  margin-top: 40px;
  text-align: center;
  font-size: 12px;
  color: {COLORS['text_tertiary']};
}}
.footer a {{
  color: {COLORS['text_link']};
  text-decoration: none;
}}

/* ── Responsive ───────────────────────────────────────────────────────── */
@media (max-width: 500px) {{
  .hero-card {{ flex-direction: column; gap: 20px; align-items: flex-start; }}
  .ring-svg {{ width: 100px; height: 100px; }}
  .dim-grid {{ grid-template-columns: 1fr 1fr; }}
  .page {{ padding: 24px 16px 60px; }}
}}

</style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <div class="header">
    <div class="header-top">
      <span class="header-title">Memory Health</span>
      <span class="header-badge">分析于 {age_str}</span>
    </div>
    <div class="header-sub">{scan_time} · {total} 条记忆</div>
  </div>

  <!-- Hero Card：健康分 + 三项统计 -->
  <div class="hero-card">
    {ring}
    <div class="hero-right">
      <div class="hero-headline">{health_headline}</div>
      <div class="hero-sub">{health_sub}</div>
      <div class="stats-row">
        <div class="stat-item">
          <div class="stat-number" style="color:{COLORS['green']}">{len(keep_entries)}</div>
          <div class="stat-label">保留</div>
        </div>
        <div class="stat-item">
          <div class="stat-number" style="color:{COLORS['orange']}">{len(review_entries)}</div>
          <div class="stat-label">复查</div>
        </div>
        <div class="stat-item">
          <div class="stat-number" style="color:{COLORS['red']}">{len(delete_entries)}</div>
          <div class="stat-label">删除</div>
        </div>
      </div>
    </div>
  </div>

  <!-- 四维评分卡片 -->
  <div class="dim-grid">
    <div class="dim-card">
      <div class="dim-name">综合分</div>
      <div class="dim-score" style="color:{COLORS['text_primary']}">{avg_composite:.1f}<span style="font-size:14px;font-weight:400;color:{COLORS['text_tertiary']}"> /5</span></div>
      {_dim_bar(avg_composite, 5.0)}
    </div>
    <div class="dim-card">
      <div class="dim-name">记忆总量</div>
      <div class="dim-score" style="color:{COLORS['text_primary']}">{total}<span style="font-size:14px;font-weight:400;color:{COLORS['text_tertiary']}"> 条</span></div>
      {_dim_bar(min(total, 200), 200)}
    </div>
    <div class="dim-card">
      <div class="dim-name">保留率</div>
      <div class="dim-score" style="color:{COLORS['text_primary']}">{int(len(keep_entries)/total*100) if total else 0}<span style="font-size:14px;font-weight:400;color:{COLORS['text_tertiary']}"> %</span></div>
      {_dim_bar(len(keep_entries), total)}
    </div>
    <div class="dim-card">
      <div class="dim-name">需处理</div>
      <div class="dim-score" style="color:{COLORS['text_primary']}">{len(review_entries)+len(delete_entries)}<span style="font-size:14px;font-weight:400;color:{COLORS['text_tertiary']}"> 条</span></div>
      {_dim_bar(len(review_entries)+len(delete_entries), total)}
    </div>
  </div>

  <!-- 记忆清单 -->
  {delete_section}
  {review_section}
  {keep_section}

  <!-- Footer -->
  <div class="footer">
    由 <a href="https://github.com/ladyiceberg/opportunity-mining/tree/main/memory-quality-mcp">Memory Quality MCP</a> 生成
  </div>

</div>

<script>
// 展开/折叠单条记忆详情
function toggleEntry(card) {{
  card.classList.toggle('expanded');
}}

// 页面加载后，给进度条加载动画
document.addEventListener('DOMContentLoaded', () => {{
  // 触发 SVG 圆环动画：初始为 0，延迟后变为真实值
  const circle = document.querySelector('circle[stroke-dasharray]');
  if (circle) {{
    const finalDash = circle.getAttribute('stroke-dasharray');
    circle.setAttribute('stroke-dasharray', '0 339.3');
    setTimeout(() => {{
      circle.setAttribute('stroke-dasharray', finalDash);
    }}, 100);
  }}
}});
</script>
</body>
</html>"""

    return html


# ── 对外接口 ───────────────────────────────────────────────────────────────────

def open_dashboard(report: StoredReport, output_path: Optional[Path] = None) -> Path:
    """
    生成 Dashboard HTML 并用系统浏览器打开。

    Args:
        report: 来自 session_store 的 StoredReport
        output_path: HTML 文件保存路径，默认写到 ~/.memory-quality-mcp/dashboard.html

    Returns:
        生成的 HTML 文件路径
    """
    if output_path is None:
        output_dir = Path.home() / ".memory-quality-mcp"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "dashboard.html"

    html = generate_dashboard_html(report)
    output_path.write_text(html, encoding="utf-8")

    # 用系统默认浏览器打开
    webbrowser.open(f"file://{output_path}")

    return output_path
