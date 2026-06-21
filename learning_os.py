#!/usr/bin/env python3
import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import re
import shutil
import contextlib
import subprocess
import sys
import time
import uuid
from pathlib import Path

from openpyxl import load_workbook


BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
STATE_PATH = BASE / "data" / "state.json"
BLACKBOARD_PATH = BASE / "blackboard" / "today.md"
TASK_MATERIALS_DIR = BASE / "task_materials"

logging.getLogger("pypdf").setLevel(logging.ERROR)


CSA_JAVA_PAGE_RANGES = {
    "Unit 1": (88, 158),
    "Unit 2": (302, 519),
    "Unit 3": (520, 644),
    "Unit 4": (402, 519),
    "Unit 5": (520, 644),
    "Unit 6": (645, 789),
    "Unit 7": (790, 907),
    "Unit 8": (790, 907),
    "Unit 9": (908, 1030),
    "Unit 10": (1155, 1254),
}


TASK_STATES = {
    "Planned",
    "Running",
    "Candidate Complete",
    "Needs Review",
    "Completed",
    "Partially Completed",
    "Failed",
    "Blocked",
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config():
    return read_json(CONFIG_PATH)


def load_state():
    if not STATE_PATH.exists():
        return {"tasks": {}, "sessions": {}, "adaptive_time": {}}
    return read_json(STATE_PATH)


def save_state(state):
    write_json(STATE_PATH, state)


def parse_date_arg(value):
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def today_date():
    return dt.date.today()


def slug(value):
    value = re.sub(r"[^A-Za-z0-9一-龥]+", "-", str(value)).strip("-")
    return value[:80] or "task"


def row_dicts(ws, header_row):
    headers = [cell.value for cell in ws[header_row]]
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if not any(v not in (None, "") for v in row):
            continue
        yield {headers[i]: row[i] if i < len(row) else None for i in range(len(headers))}


def normalize_plan_mmdd(raw_date, year):
    if raw_date in (None, ""):
        return None
    if isinstance(raw_date, dt.datetime):
        return raw_date.date()
    if isinstance(raw_date, dt.date):
        return raw_date
    text = str(raw_date).strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})$", text)
    if not m:
        return None
    return dt.date(year, int(m.group(1)), int(m.group(2)))


def parse_day_range(raw):
    text = str(raw or "")
    nums = [int(n) for n in re.findall(r"\d+", text)]
    if not nums:
        return None
    if len(nums) == 1:
        return nums[0], nums[0]
    return nums[0], nums[1]


def adaptive_minutes(state, task_key, default_min, config):
    return int(state.get("adaptive_time", {}).get(task_key, default_min))


def find_existing_path(config, candidate):
    if not candidate or str(candidate).strip() in {"—", "-"}:
        return None
    text = str(candidate).strip()
    workspace = Path(config["workspace_root"])
    if Path(text).exists():
        return str(Path(text))
    basename = Path(text.replace("\\", "/")).name
    if not basename:
        return None
    matches = list(workspace.rglob(basename))
    if matches:
        return str(matches[0])
    return None


def abs_workspace_path(config, relative_path):
    if not relative_path:
        return None
    path = Path(relative_path)
    if not path.is_absolute():
        path = Path(config["workspace_root"]) / path
    return str(path) if path.exists() else None


def local_fallback_resources(config, course, unit, include_practice=False):
    fallbacks = config.get("local_resource_fallbacks", {}).get(course, {})
    resources = []
    for label in ["workbook", "dashboard", "summary"]:
        target = abs_workspace_path(config, fallbacks.get(label))
        if target:
            resources.append({"label": f"local_{label}", "target": target})
    unit_target = abs_workspace_path(config, fallbacks.get("unit_pages", {}).get(str(unit)))
    if unit_target:
        resources.append({"label": "local_unit_page", "target": unit_target})
    if include_practice:
        practice_target = abs_workspace_path(config, fallbacks.get("practice_pdfs", {}).get(str(unit)))
        if practice_target:
            resources.append({"label": "local_practice_pdf", "target": practice_target})
    return resources


def dedupe_resources(resources):
    seen = set()
    clean = []
    for resource in resources:
        target = resource.get("target")
        if not target or target in seen:
            continue
        seen.add(target)
        clean.append(resource)
    return clean


def pdf_excerpt_path(source_path, start_page, end_page, label):
    source = Path(source_path)
    digest = hashlib.sha1(f"{source}:{start_page}:{end_page}:{label}".encode("utf-8")).hexdigest()[:10]
    safe_label = slug(label)
    return TASK_MATERIALS_DIR / f"{safe_label}_p{start_page}-{end_page}_{digest}.pdf"


def create_pdf_excerpt(source_path, start_page, end_page, label):
    source = Path(source_path)
    if not source.exists():
        return None
    output = pdf_excerpt_path(source, start_page, end_page, label)
    if output.exists() and output.stat().st_size > 0:
        return str(output)
    TASK_MATERIALS_DIR.mkdir(parents=True, exist_ok=True)
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(str(source))
    total = len(reader.pages)
    start = max(1, min(int(start_page), total))
    end = max(start, min(int(end_page), total))
    writer = PdfWriter()
    for page_index in range(start - 1, end):
        writer.add_page(reader.pages[page_index])
    metadata = {
        "/Title": f"AP Learning OS - {label}",
        "/Subject": f"{source.name} pages {start}-{end}"
    }
    try:
        writer.add_metadata(metadata)
    except Exception:
        pass
    with output.open("wb") as f:
        writer.write(f)
    return str(output)


def flatten_outline_items(outline):
    for item in outline:
        if isinstance(item, list):
            yield from flatten_outline_items(item)
        else:
            yield item


def pdf_section_index(source_path, cache_key):
    cache_path = BASE / "data" / f"{cache_key}_section_index.json"
    source = Path(source_path)
    if cache_path.exists():
        cached = read_json(cache_path)
        if cached.get("source_mtime") == source.stat().st_mtime:
            return cached["sections"]
    from pypdf import PdfReader
    reader = PdfReader(str(source))
    sections = {}
    for item in flatten_outline_items(reader.outline):
        title = getattr(item, "title", str(item)).replace("\x00", "")
        m = re.search(r"\b(\d+)\.(\d+)\b", title)
        if not m:
            continue
        try:
            page = reader.get_destination_page_number(item) + 1
        except Exception:
            continue
        sections[f"{m.group(1)}.{m.group(2)}"] = page
    write_json(cache_path, {"source": str(source), "source_mtime": source.stat().st_mtime, "sections": sections})
    return sections


def next_section_page(section_pages, section):
    parts = section.split(".")
    if len(parts) != 2:
        return None
    ch, sec = int(parts[0]), int(parts[1])
    candidates = []
    for key, page in section_pages.items():
        m = re.match(r"^(\d+)\.(\d+)$", key)
        if not m:
            continue
        kch, ksec = int(m.group(1)), int(m.group(2))
        if (kch, ksec) > (ch, sec):
            candidates.append(page)
    return min(candidates) if candidates else None


def parse_stewart_sections(text):
    if not text or "Stewart" not in str(text):
        return []
    raw = str(text)
    matches = []
    pattern = re.compile(r"(\d+)\.(\d+)(?:\s*-\s*(?:(\d+)\.)?(\d+))?")
    for m in pattern.finditer(raw):
        start = f"{m.group(1)}.{m.group(2)}"
        if m.group(4):
            end_ch = m.group(3) or m.group(1)
            end = f"{end_ch}.{m.group(4)}"
        else:
            end = start
        matches.append((start, end))
    return matches


def stewart_excerpt_resources(config, row):
    material = config.get("canonical_materials", {}).get("AP_Calculus_BC", {}).get("stewart_textbook")
    if not material or not Path(material).exists():
        return []
    refs = parse_stewart_sections(row.get("课件/课本参考"))
    if not refs:
        return []
    section_pages = pdf_section_index(material, "stewart")
    resources = []
    for start_section, end_section in refs:
        start_page = section_pages.get(start_section)
        end_start_page = section_pages.get(end_section)
        if not start_page or not end_start_page:
            continue
        next_page = next_section_page(section_pages, end_section)
        end_page = (next_page - 1) if next_page else (end_start_page + 12)
        label = f"BC {row.get('Unit')} {row.get('天数')} Stewart {start_section}-{end_section}"
        excerpt = create_pdf_excerpt(material, start_page, end_page, label)
        if excerpt:
            resources.append({
                "label": "task_excerpt_stewart",
                "target": excerpt,
                "source": material,
                "page_range": [start_page, end_page],
                "sections": [start_section, end_section]
            })
    resources.append({"label": "canonical_stewart_textbook", "target": material})
    master = config.get("canonical_materials", {}).get("AP_Calculus_BC", {}).get("ap_master_packet")
    if master and Path(master).exists():
        resources.append({"label": "canonical_ap_master_packet", "target": master})
    return resources


def csa_excerpt_resources(config, unit, title, include_practice=False):
    material = config.get("canonical_materials", {}).get("AP_CSA", {}).get("java_textbook")
    resources = []
    if material and Path(material).exists() and unit in CSA_JAVA_PAGE_RANGES:
        start_page, end_page = csa_daily_page_range(unit, title)
        excerpt = create_pdf_excerpt(material, start_page, end_page, f"CSA {unit} Java Illuminated")
        if excerpt:
            resources.append({
                "label": "task_excerpt_java_illuminated",
                "target": excerpt,
                "source": material,
                "page_range": [start_page, end_page]
            })
        resources.append({"label": "canonical_java_textbook", "target": material})
    master = config.get("canonical_materials", {}).get("AP_CSA", {}).get("ap_master_packet")
    if master and Path(master).exists():
        resources.append({"label": "canonical_ap_master_packet", "target": master})
    return resources


def print_packet_text_index(config):
    packet = config.get("dated_print_packet", {})
    pdf = packet.get("pdf")
    if not pdf or not Path(pdf).exists():
        return None
    source = Path(pdf)
    cache_path = BASE / "data" / "dated_print_packet_text_index.json"
    if cache_path.exists():
        cached = read_json(cache_path)
        if cached.get("source_mtime") == source.stat().st_mtime:
            return cached
    from pypdf import PdfReader
    pages = []
    with open(os.devnull, "w") as devnull:
        with contextlib.redirect_stderr(devnull):
            reader = PdfReader(str(source))
            for idx, page in enumerate(reader.pages, start=1):
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                compact = " ".join(text.split())
                pages.append({"page": idx, "text": compact[:4000]})
    index = {"source": str(source), "source_mtime": source.stat().st_mtime, "pages": pages}
    write_json(cache_path, index)
    return index


def keyword_score(text, keywords):
    lowered = text.lower()
    score = 0
    for keyword, weight in keywords:
        if not keyword:
            continue
        occurrences = lowered.count(keyword.lower())
        score += occurrences * weight
    return score


def topic_print_keywords(course, unit, title, row=None):
    title = str(title or "")
    unit = str(unit or "")
    keywords = []
    if course == "AP_Calculus_BC":
        keywords.extend([
            ("AP Calculus BC", 1),
            ("CALCULUS BC", 1),
            ("derivative", 5),
            ("differentiation", 4),
            ("tangent", 3),
            ("rate of change", 4),
            ("导数", 5),
            ("切线", 4),
        ])
        if row:
            refs = parse_stewart_sections(row.get("课件/课本参考"))
            for start, end in refs:
                keywords.append((start, 2))
                if end != start:
                    keywords.append((end, 2))
        if "Unit 1" in unit or "极限" in title:
            keywords.extend([("limit", 5), ("continuity", 4), ("horizontal asymptote", 3), ("极限", 5)])
        if "Unit 2" in unit or "导数" in title:
            keywords.extend([
                ("defining the derivative", 14),
                ("definition of derivative", 12),
                ("derivative notation", 10),
                ("tangent line", 10),
                ("basic derivative", 6),
                ("Topic 2.D", 8),
                ("slope field", -12),
            ])
        if "Unit 3" in unit:
            keywords.extend([("chain rule", 7), ("implicit", 5), ("inverse", 4)])
        if "Unit 4" in unit:
            keywords.extend([("related rates", 6), ("motion", 5), ("linear approximation", 4)])
    elif course == "AP_CSA":
        keywords.extend([
            ("AP Computer Science A", 5),
            ("Computer Science A", 4),
            ("Java", 3),
        ])
        if "Unit 1" in unit:
            keywords.extend([
                ("UNIT 1", 5),
                ("Using Objects", 5),
                ("Introduction to Java", 12),
                ("Primitive data type", 12),
                ("primitive types", 10),
                ("data types", 10),
                ("expressions", 10),
                ("output", 8),
                ("main method", 8),
                ("Methods", 4),
                ("variable", 3),
                ("expression", 4),
                ("data type", 4),
                ("assignment", 4),
                ("String", 3),
                ("变量", 5),
                ("表达式", 5),
                ("Scope and Access", -20),
                ("Global and Local Variables", -20),
                ("constructor", -6),
            ])
        if "Unit 2" in unit:
            keywords.extend([("boolean", 5), ("if", 3), ("loop", 5), ("iteration", 5), ("while", 4), ("for", 4)])
        if "Unit 3" in unit:
            keywords.extend([("class", 5), ("constructor", 5), ("object", 4), ("method", 4)])
        if "刷题" in title:
            keywords.extend([("Test Booklet", 5), ("Scoring Guide", 3)])
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", title):
        keywords.append((token, 2))
    return keywords


def best_topic_page_range(index, keywords, max_pages=10):
    pages = index.get("pages", [])
    scored = []
    for page in pages:
        score = keyword_score(page.get("text", ""), keywords)
        if score > 0:
            scored.append((score, page["page"]))
    if not scored:
        return None
    scored.sort(reverse=True)
    anchor_page = scored[0][1]
    best_start = anchor_page
    best_end = min(best_start + max_pages - 1, pages[-1]["page"])
    return [best_start, best_end], scored[:8]


def print_packet_override_range(course, unit, title):
    title = str(title or "")
    unit = str(unit or "")
    if course == "AP_CSA" and unit == "Unit 1":
        if any(k in title for k in ["1.1-1.3", "算法", "变量", "数据类型", "表达式", "输出"]):
            return [569, 578], "manual_topic_override:csa_unit1_intro"
    if course == "AP_Calculus_BC" and unit == "Unit 2":
        if any(k in title for k in ["导数定义", "切线斜率", "derivative", "tangent"]):
            return [3185, 3192], "manual_topic_override:bc_unit2_derivative_definition"
    return None, None


def topic_print_packet_resources(config, course, unit, title, row=None):
    packet = config.get("dated_print_packet", {})
    index = print_packet_text_index(config)
    if not index:
        return []
    page_range, match = print_packet_override_range(course, unit, title)
    hits = []
    if not page_range:
        keywords = topic_print_keywords(course, unit, title, row)
        result = best_topic_page_range(index, keywords)
        if not result:
            return []
        page_range, hits = result
        match = "topic_keywords"
    start_page, end_page = page_range
    pdf = index["source"]
    label = f"{course} topic print packet {unit} {title}"
    excerpt = create_pdf_excerpt(pdf, start_page, end_page, label)
    if not excerpt:
        return []
    return [{
        "label": f"supplemental_print_packet_{'bc' if course == 'AP_Calculus_BC' else 'csa'}",
        "target": excerpt,
        "source": pdf,
        "page_range": [start_page, end_page],
        "match": match,
        "top_hits": hits,
        "note": packet.get("note", "")
    }]


def csa_daily_page_range(unit, title):
    text = str(title or "")
    if unit == "Unit 1":
        if any(k in text for k in ["1.1", "1.2", "1.3", "算法", "变量", "数据类型", "表达式", "输出"]):
            return (92, 139)
        if any(k in text for k in ["1.4", "Scanner", "输入"]):
            return (140, 158)
        if any(k in text for k in ["1.5", "1.6", "类型转换", "复合赋值"]):
            return (116, 139)
        if any(k in text for k in ["1.7", "1.8", "API", "库", "注释"]):
            return (41, 87)
        if any(k in text for k in ["1.9", "1.10", "方法签名", "调用"]):
            return (159, 200)
        if any(k in text for k in ["Math", "对象实例", "new关键字"]):
            return (159, 200)
        if any(k in text for k in ["String", "substring", "indexOf", "equals"]):
            return (159, 200)
    if unit == "Unit 2":
        if any(k in text for k in ["if", "布尔", "德摩根", "选择"]):
            return (302, 401)
        if any(k in text for k in ["while", "for", "循环", "迭代", "嵌套"]):
            return (402, 519)
    return CSA_JAVA_PAGE_RANGES.get(unit, (88, 158))


def build_csa_tasks(config, state, current_date):
    plan = Path(config["plans"]["AP_CSA"])
    wb = load_workbook(plan, data_only=True, read_only=True)
    ws = wb["每日刷题计划"]
    tasks = []
    for row in row_dicts(ws, 3):
        row_date = normalize_plan_mmdd(row.get("日期"), config["planner"]["csa_year"])
        if row_date != current_date:
            continue
        practice_ids = str(row.get("今日刷题编号") or "")
        is_practice = "—" not in practice_ids and practice_ids.strip() not in {"", "-"}
        kind = "CSA_PRACTICE" if is_practice else "CSA_CONCEPT"
        default_min = config["planner"]["default_targets_min"][kind]
        task_key = f"CSA:{row.get('Unit')}:{row.get('天数')}:{kind}"
        target_min = adaptive_minutes(state, task_key, default_min, config)
        resources = []
        for label, col in [("question_file", "题目文件"), ("answer_file", "答案文件")]:
            found = find_existing_path(config, row.get(col))
            if found:
                resources.append({"label": label, "target": found})
        resources.extend(csa_excerpt_resources(config, row.get("Unit"), row.get("学习内容"), include_practice=is_practice))
        resources.extend(topic_print_packet_resources(config, "AP_CSA", row.get("Unit"), row.get("学习内容"), row))
        resources.extend(local_fallback_resources(config, "AP_CSA", row.get("Unit"), include_practice=is_practice))
        resources = dedupe_resources(resources)
        tasks.append({
            "id": f"CSA-{current_date.isoformat()}-{slug(row.get('天数'))}-{kind}",
            "task_key": task_key,
            "course": "AP_CSA",
            "kind": kind,
            "state": "Planned",
            "date": current_date.isoformat(),
            "unit": row.get("Unit"),
            "title": f"CSA {row.get('Unit')} {row.get('天数')} - {row.get('学习内容')}",
            "target_min": target_min,
            "observable_goal": (
                f"Open CSA materials for {row.get('学习内容')} and work for at least {target_min} minutes."
            ),
            "completion_criteria": [
                f"CSA-related resource/window remains active for about {target_min} minutes",
                "Start/end screenshots exist",
                "uone reviews evidence and overwrites final status"
            ],
            "resources": resources,
            "launch": [
                {"type": "url", "target": config["urls"]["khan_ap_csa"]},
                {"type": "app", "target": config["apps"]["notes"]},
                {"type": "app", "target": config["apps"]["editor"]}
            ],
            "source": {"workbook": str(plan), "sheet": "每日刷题计划", "row": row},
        })
    return tasks


def build_bc_tasks(config, state, current_date):
    plan = Path(config["plans"]["AP_Calculus_BC"])
    wb = load_workbook(plan, data_only=True, read_only=True)
    ws = wb["每日计划"]
    bc_rows = []
    cumulative_day = 0
    for row in row_dicts(ws, 3):
        rng = parse_day_range(row.get("天数"))
        if not rng:
            continue
        start, end = rng
        duration_days = max(1, end - start + 1)
        global_start = cumulative_day + 1
        global_end = cumulative_day + duration_days
        cumulative_day = global_end
        bc_rows.append((row, global_start, global_end))
    anchor = config.get("planner", {}).get("bc_anchor")
    if anchor:
        anchor_date = parse_date_arg(anchor["date"])
        anchor_global_day = None
        for row, global_start, global_end in bc_rows:
            if str(row.get("Unit")) == str(anchor.get("unit")) and str(row.get("天数")) == str(anchor.get("day")):
                anchor_global_day = global_start
                break
        if anchor_global_day is None:
            raise SystemExit(f"BC anchor not found: {anchor}")
        global_day_number = anchor_global_day + (current_date - anchor_date).days
    else:
        day1 = parse_date_arg(config["planner"]["bc_day_1_date"])
        global_day_number = (current_date - day1).days + 1
    if global_day_number < 1:
        return []
    tasks = []
    for row, global_start, global_end in bc_rows:
        if not (global_start <= global_day_number <= global_end):
            continue
        task_key = f"BC:{row.get('Unit')}:{row.get('天数')}:RESOURCE"
        default_min = config["planner"]["default_targets_min"]["BC_RESOURCE_WORK"]
        target_min = adaptive_minutes(state, task_key, default_min, config)
        primary = find_existing_path(config, row.get("文件名（可直接打开）"))
        resources = []
        if primary:
            resources.append({"label": "primary_resource", "target": primary})
        for label, col in [("reference", "课件/课本参考"), ("practice", "配套练习/答案")]:
            target = find_existing_path(config, row.get(col))
            if target:
                resources.append({"label": label, "target": target})
        resources.extend(stewart_excerpt_resources(config, row))
        resources.extend(topic_print_packet_resources(config, "AP_Calculus_BC", row.get("Unit"), row.get("学习内容"), row))
        resources.extend(local_fallback_resources(config, "AP_Calculus_BC", row.get("Unit"), include_practice=True))
        resources = dedupe_resources(resources)
        tasks.append({
            "id": f"BC-{current_date.isoformat()}-DAY{global_day_number}-{slug(row.get('Unit'))}",
            "task_key": task_key,
            "course": "AP_Calculus_BC",
            "kind": "BC_RESOURCE_WORK",
            "state": "Planned",
            "date": current_date.isoformat(),
            "unit": row.get("Unit"),
            "title": f"BC {row.get('Unit')} {row.get('天数')} - {row.get('学习内容')}",
            "target_min": target_min,
            "observable_goal": (
                f"Open BC resource for {row.get('学习内容')} and work for at least {target_min} minutes."
            ),
            "completion_criteria": [
                f"BC resource/Khan/GoodNotes window evidence for about {target_min} minutes",
                "Start/end screenshots exist",
                "uone reviews evidence and overwrites final status"
            ],
            "resources": resources,
            "launch": [
                {"type": "url", "target": config["urls"].get("khan_calculus_bc_units", {}).get(str(row.get("Unit")), config["urls"]["khan_calculus_bc"])},
                {"type": "app", "target": config["apps"]["notes"]},
                {"type": "resource", "target": primary} if primary else {"type": "app", "target": config["apps"]["pdf"]}
            ],
            "source": {
                "workbook": str(plan),
                "sheet": "每日计划",
                "row": row,
                "mapped_global_day_number": global_day_number,
                "mapped_global_day_range": [global_start, global_end]
            },
        })
    return tasks


def add_error_log_task(config, state, current_date):
    key = f"ERROR_LOG:{current_date.isoformat()}"
    default_min = config["planner"]["default_targets_min"]["CSA_ERROR_LOG"]
    target_min = adaptive_minutes(state, key, default_min, config)
    return {
        "id": f"ERRORLOG-{current_date.isoformat()}",
        "task_key": key,
        "course": "GLOBAL",
        "kind": "ERROR_LOG",
        "state": "Planned",
        "date": current_date.isoformat(),
        "unit": "All",
        "title": "Error Log Review",
        "target_min": target_min,
        "observable_goal": f"Open the error log/notes and review mistakes for at least {target_min} minutes.",
        "completion_criteria": [
            f"GoodNotes or notes window active for about {target_min} minutes",
            "Review screenshot exists",
            "uone reviews evidence and overwrites final status"
        ],
        "resources": [],
        "launch": [{"type": "app", "target": config["apps"]["notes"]}],
        "source": {"generated": True}
    }


def generate_today(config, state, current_date):
    tasks = []
    tasks.extend(build_bc_tasks(config, state, current_date))
    tasks.extend(build_csa_tasks(config, state, current_date))
    if tasks:
        tasks.append(add_error_log_task(config, state, current_date))
    generated_ids = {task["id"] for task in tasks}
    for task_id, existing in list(state["tasks"].items()):
        if existing.get("date") == current_date.isoformat() and task_id not in generated_ids:
            if existing.get("state") in {"Planned", "Needs Review", "Failed", "Partially Completed"}:
                del state["tasks"][task_id]
    for task in tasks:
        existing = state["tasks"].get(task["id"], {})
        task["state"] = existing.get("state", task["state"])
        task["last_session_id"] = existing.get("last_session_id")
        state["tasks"][task["id"]] = task
    save_state(state)
    write_blackboard(tasks, current_date)
    return tasks


def write_blackboard(tasks, current_date):
    lines = [
        f"# AP Learning OS Blackboard - {current_date.isoformat()}",
        "",
        "Rule: detectors produce evidence only. Final completion requires uone review.",
        "",
    ]
    if not tasks:
        lines.append("No planned tasks found for this date.")
    for task in tasks:
        lines.extend([
            f"## [{task['state']}] {task['id']}",
            "",
            f"- Course: {task['course']}",
            f"- Unit: {task['unit']}",
            f"- Target time: {task['target_min']} min",
            f"- Observable goal: {task['observable_goal']}",
            "- Completion criteria:",
        ])
        for criterion in task["completion_criteria"]:
            lines.append(f"  - {criterion}")
        if task.get("resources"):
            lines.append("- Resources:")
            for resource in task["resources"]:
                lines.append(f"  - {resource['label']}: {resource['target']}")
        lines.append("")
    BLACKBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    BLACKBOARD_PATH.write_text("\n".join(lines), encoding="utf-8")


def run(cmd, check=False):
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def osascript(script):
    return run(["osascript", "-e", script]).stdout.strip()


def frontmost_window():
    script = '''
tell application "System Events"
  set frontApp to name of first application process whose frontmost is true
  set winTitle to ""
  try
    tell process frontApp
      if count of windows > 0 then set winTitle to name of front window
    end tell
  end try
  return frontApp & " | " & winTitle
end tell
'''
    try:
        value = osascript(script)
    except Exception as exc:
        value = f"UNKNOWN | {exc}"
    app, _, title = value.partition(" | ")
    return {"app": app, "window": title, "timestamp": dt.datetime.now().isoformat(timespec="seconds")}


def capture_screenshot(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    result = run(["screencapture", "-x", str(path)])
    ok = result.returncode == 0 and path.exists()
    if not ok:
        error_path = path.parent / "screenshot_errors.log"
        error_path.write_text(
            f"{dt.datetime.now().isoformat(timespec='seconds')} failed to capture {path.name}\n"
            f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}\n"
            "macOS may need Screen Recording permission for the terminal/Codex process.\n",
            encoding="utf-8"
        )
    return ok


def launch_item(item):
    typ = item.get("type")
    target = item.get("target")
    if not target:
        return
    if typ == "url":
        subprocess.Popen(["open", target])
    elif typ == "app":
        subprocess.Popen(["open", "-a", target])
    elif typ == "resource":
        if Path(target).exists():
            subprocess.Popen(["open", target])


def launch_task_resources(task):
    open_labels = {
        "task_excerpt_stewart",
        "task_excerpt_java_illuminated",
        "supplemental_print_packet_bc",
        "supplemental_print_packet_csa",
        "question_file",
        "local_practice_pdf",
        "local_unit_page",
    }
    for resource in task.get("resources", []):
        if resource.get("label") not in open_labels:
            continue
        target = resource.get("target")
        if target and Path(target).exists():
            subprocess.Popen(["open", target])


def set_task_state(state, task_id, new_state):
    if new_state not in TASK_STATES:
        raise ValueError(f"invalid state: {new_state}")
    task = state["tasks"][task_id]
    old = task.get("state", "Planned")
    task["state"] = new_state
    task.setdefault("transitions", []).append({
        "from": old,
        "to": new_state,
        "timestamp": dt.datetime.now().isoformat(timespec="seconds")
    })


def compute_signal_score(task, samples, session_dir, observed_elapsed_min=None):
    target_min = float(task["target_min"])
    elapsed_min = float(observed_elapsed_min or 0)
    if elapsed_min <= 0 and samples:
        first = dt.datetime.fromisoformat(samples[0]["timestamp"])
        last = dt.datetime.fromisoformat(samples[-1]["timestamp"])
        elapsed_min = max(elapsed_min, (last - first).total_seconds() / 60)
    screenshots = list(session_dir.glob("*.png"))
    time_score = min(1.0, elapsed_min / target_min) if target_min else 0
    screenshot_score = min(1.0, len(screenshots) / 2)
    window_score = 0.0
    course_terms = {
        "AP_CSA": ["Safari", "Code", "GoodNotes", "Java", "Khan"],
        "AP_Calculus_BC": ["Safari", "Preview", "GoodNotes", "Khan", "Calculus"],
        "GLOBAL": ["GoodNotes", "Notes", "Preview"]
    }.get(task["course"], [])
    if samples and course_terms:
        hits = 0
        for sample in samples:
            haystack = f"{sample.get('app','')} {sample.get('window','')}".lower()
            if any(term.lower() in haystack for term in course_terms):
                hits += 1
        window_score = hits / len(samples)
    score = 0.5 * time_score + 0.25 * screenshot_score + 0.25 * window_score
    return {
        "score": round(score, 3),
        "elapsed_min_estimate": round(elapsed_min, 2),
        "screenshots": len(screenshots),
        "window_match_ratio": round(window_score, 3)
    }


def build_review_packet(session, task, signal_summary, session_dir):
    packet = session_dir / "review_packet.md"
    lines = [
        f"# uone Review Packet - {session['id']}",
        "",
        f"- Task: {task['id']}",
        f"- Title: {task['title']}",
        f"- Target: {task['target_min']} min",
        f"- System recommendation: {session['recommendation']}",
        f"- Signal score: {signal_summary['score']}",
        f"- Estimated elapsed: {signal_summary['elapsed_min_estimate']} min",
        f"- Window match ratio: {signal_summary['window_match_ratio']}",
        f"- Screenshots: {signal_summary['screenshots']}",
        "",
        "## Completion Criteria",
    ]
    for criterion in task["completion_criteria"]:
        lines.append(f"- {criterion}")
    lines.extend(["", "## Evidence Files"])
    for path in sorted(session_dir.iterdir()):
        if path.name != "review_packet.md":
            lines.append(f"- {path}")
    if (session_dir / "screenshot_errors.log").exists():
        lines.extend([
            "",
            "## Capture Warnings",
            "",
            "Screenshot capture failed. Grant Screen Recording permission to the terminal/Codex process in macOS System Settings, then rerun the session."
        ])
    lines.extend([
        "",
        "## uone Decision",
        "",
        "Run one of:",
        "",
        f"```bash",
        f"python3 {BASE / 'learning_os.py'} review --session {session['id']} --status completed --notes \"uone confirmed\"",
        f"python3 {BASE / 'learning_os.py'} review --session {session['id']} --status partially_completed --notes \"what remains\"",
        f"python3 {BASE / 'learning_os.py'} review --session {session['id']} --status not_completed --notes \"why\"",
        f"```",
    ])
    packet.write_text("\n".join(lines), encoding="utf-8")
    return str(packet)


def start_session(args):
    config = load_config()
    state = load_state()
    if args.task not in state["tasks"]:
        raise SystemExit(f"Unknown task id: {args.task}. Run `today` first.")
    task = state["tasks"][args.task]
    session_id = f"S-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    session_dir = BASE / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    duration_min = args.duration_min if args.duration_min is not None else float(task["target_min"])
    set_task_state(state, args.task, "Running")
    task["last_session_id"] = session_id
    session = {
        "id": session_id,
        "task_id": args.task,
        "started_at": dt.datetime.now().isoformat(timespec="seconds"),
        "duration_min": duration_min,
        "state": "Running",
        "samples": [],
        "session_dir": str(session_dir)
    }
    state["sessions"][session_id] = session
    save_state(state)
    for item in task.get("launch", []):
        launch_item(item)
    launch_task_resources(task)
    if config["signals"]["screenshot_at_start"]:
        capture_screenshot(session_dir / "start.png")
    total_sec = max(1, int(duration_min * 60))
    interval = int(config["signals"]["window_sample_interval_sec"])
    midpoint_done = False
    start = time.time()
    while time.time() - start < total_sec:
        session["samples"].append(frontmost_window())
        elapsed = time.time() - start
        if config["signals"]["screenshot_midpoint"] and not midpoint_done and elapsed >= total_sec / 2:
            capture_screenshot(session_dir / "midpoint.png")
            midpoint_done = True
        time.sleep(min(interval, max(0.2, total_sec - elapsed)))
    if config["signals"]["screenshot_at_end"]:
        capture_screenshot(session_dir / "end.png")
    observed_elapsed_min = (time.time() - start) / 60
    (session_dir / "window_samples.json").write_text(
        json.dumps(session["samples"], ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    signal_summary = compute_signal_score(task, session["samples"], session_dir, observed_elapsed_min)
    (session_dir / "signal_summary.json").write_text(
        json.dumps(signal_summary, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    threshold = config["completion_policy"]["candidate_threshold"]
    recommendation = "Candidate Complete" if signal_summary["score"] >= threshold else "Needs Review"
    session["state"] = "Needs Review"
    session["recommendation"] = recommendation
    session["ended_at"] = dt.datetime.now().isoformat(timespec="seconds")
    session["signal_summary"] = signal_summary
    set_task_state(state, args.task, recommendation)
    if recommendation == "Candidate Complete":
        set_task_state(state, args.task, "Needs Review")
    packet = build_review_packet(session, task, signal_summary, session_dir)
    session["review_packet"] = packet
    state["sessions"][session_id] = session
    save_state(state)
    print(json.dumps({"session_id": session_id, "review_packet": packet, "recommendation": recommendation}, ensure_ascii=False, indent=2))


def apply_review(session_id, status, notes="", adjust_min=None, review_source="manual_cli"):
    config = load_config()
    state = load_state()
    session = state["sessions"].get(session_id)
    if not session:
        raise SystemExit(f"Unknown session id: {session_id}")
    task_id = session["task_id"]
    task = state["tasks"][task_id]
    mapping = {
        "completed": "Completed",
        "partially_completed": "Partially Completed",
        "not_completed": "Failed",
        "failed": "Failed",
        "blocked": "Blocked"
    }
    final_state = mapping[status]
    set_task_state(state, task_id, final_state)
    session["uone_review"] = {
        "status": status,
        "notes": notes or "",
        "adjust_min": adjust_min,
        "source": review_source,
        "reviewed_at": dt.datetime.now().isoformat(timespec="seconds")
    }
    session["state"] = final_state
    key = task["task_key"]
    current_min = int(task["target_min"])
    adaptive = state.setdefault("adaptive_time", {})
    if final_state == "Completed":
        adaptive.pop(key, None)
    elif final_state in {"Partially Completed", "Failed"}:
        bump = int(adjust_min if adjust_min is not None else config["completion_policy"]["time_escalation_min"])
        cap = int(config["completion_policy"]["max_target_min"])
        adaptive[key] = min(cap, current_min + bump)
    state["sessions"][session_id] = session
    save_state(state)
    result = {"task_id": task_id, "final_state": final_state, "next_target_min": state.get("adaptive_time", {}).get(key)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def review_session(args):
    apply_review(args.session, args.status, args.notes or "", args.adjust_min, "manual_cli")


def parse_uone_review_text(text):
    normalized = re.sub(r"\s+", "", text.lower())
    adjust_min = None
    m = re.search(r"(?:多定|加|增加|延长|再来|再做|追加)(\d{1,3})(?:分钟|min|m)?", normalized)
    if not m:
        m = re.search(r"(\d{1,3})(?:分钟|min|m)", normalized)
    if m:
        adjust_min = int(m.group(1))
    if any(word in normalized for word in ["完成了", "已完成", "通过", "可以过", "算完成", "done", "completed"]):
        status = "completed"
    elif any(word in normalized for word in ["部分完成", "做了一部分", "差一点", "快完成", "partial"]):
        status = "partially_completed"
    elif any(word in normalized for word in ["卡住", "打不开", "无法", "没法", "blocked"]):
        status = "blocked"
    elif any(word in normalized for word in ["没有完成", "没完成", "未完成", "不通过", "重做", "notcompleted", "failed"]):
        status = "not_completed"
    elif adjust_min is not None:
        status = "not_completed"
    else:
        raise SystemExit("Could not infer uone status from text. Use clearer words: 完成了 / 没完成 / 部分完成 / 卡住, optionally 多定20分钟.")
    return status, adjust_min


def review_text_session(args):
    text = args.text or ""
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    status, adjust_min = parse_uone_review_text(text)
    apply_review(args.session, status, text, adjust_min, "uone_text_or_ocr")


def list_tasks(args):
    state = load_state()
    for task_id, task in state["tasks"].items():
        if args.date and task.get("date") != args.date:
            continue
        print(f"{task_id}\t{task.get('state')}\t{task.get('target_min')}m\t{task.get('title')}")


def material_report(args):
    state = load_state()
    date_text = args.date
    tasks = [t for t in state["tasks"].values() if not date_text or t.get("date") == date_text]
    for task in tasks:
        print(f"\n{task['id']}\n{task['title']}")
        for resource in task.get("resources", []):
            label = resource.get("label")
            target = resource.get("target")
            if args.core_only and not (
                str(label).startswith("task_excerpt")
                or str(label).startswith("supplemental_print_packet")
                or label in {"question_file", "local_practice_pdf", "local_unit_page"}
            ):
                continue
            exists = Path(target).exists() if target else False
            page_range = resource.get("page_range")
            page_text = f" p{page_range[0]}-{page_range[1]}" if page_range else ""
            print(f"- {label}{page_text}: {'OK' if exists else 'MISSING'}")
            print(f"  {target}")


def reset_task(args):
    state = load_state()
    if args.task not in state["tasks"]:
        raise SystemExit(f"Unknown task id: {args.task}")
    set_task_state(state, args.task, "Planned")
    state["tasks"][args.task]["last_session_id"] = None
    save_state(state)
    print(json.dumps({"task_id": args.task, "state": "Planned"}, ensure_ascii=False, indent=2))


def cmd_today(args):
    config = load_config()
    state = load_state()
    current_date = parse_date_arg(args.date) if args.date else today_date()
    tasks = generate_today(config, state, current_date)
    print(f"Wrote {len(tasks)} tasks to {BLACKBOARD_PATH}")
    for task in tasks:
        print(f"{task['id']}\t{task['target_min']}m\t{task['title']}")


def main():
    parser = argparse.ArgumentParser(description="AP Learning OS workflow engine")
    sub = parser.add_subparsers(dest="command", required=True)
    p_today = sub.add_parser("today", help="generate today's blackboard tasks")
    p_today.add_argument("--date", help="YYYY-MM-DD")
    p_today.set_defaults(func=cmd_today)
    p_start = sub.add_parser("start", help="start and monitor a task session")
    p_start.add_argument("--task", required=True)
    p_start.add_argument("--duration-min", type=float)
    p_start.set_defaults(func=start_session)
    p_review = sub.add_parser("review", help="apply uone final review")
    p_review.add_argument("--session", required=True)
    p_review.add_argument("--status", required=True, choices=["completed", "partially_completed", "not_completed", "failed", "blocked"])
    p_review.add_argument("--notes")
    p_review.add_argument("--adjust-min", type=int, help="minutes to add to the next attempt when not completed")
    p_review.set_defaults(func=review_session)
    p_review_text = sub.add_parser("review-text", help="apply uone review from chat/OCR text")
    p_review_text.add_argument("--session", required=True)
    p_review_text.add_argument("--text", help="uone chat/OCR text")
    p_review_text.add_argument("--file", help="file containing uone chat/OCR text")
    p_review_text.set_defaults(func=review_text_session)
    p_list = sub.add_parser("tasks", help="list known tasks")
    p_list.add_argument("--date")
    p_list.set_defaults(func=list_tasks)
    p_materials = sub.add_parser("materials", help="report task resource mappings")
    p_materials.add_argument("--date")
    p_materials.add_argument("--core-only", action="store_true")
    p_materials.set_defaults(func=material_report)
    p_reset = sub.add_parser("reset-task", help="reset a task to Planned after accidental/test start")
    p_reset.add_argument("--task", required=True)
    p_reset.set_defaults(func=reset_task)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
