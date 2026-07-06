#!/usr/bin/env python3
"""Batch resume extraction test against ground_truth.json (run via odoo shell)."""
import base64
import json
import re
import sys
from pathlib import Path

DATASET = Path("/home/pranjal/Downloads/indian_resumes_dataset/output_resumes")
GROUND_TRUTH = DATASET / "ground_truth.json"
IMAGE_SAMPLES = [
    Path("/home/pranjal/.cursor/projects/home-pranjal-odoo-odoo-19-modules/assets/image-8712caf4-6d46-41cc-8a09-158438f87d3c.png"),
    Path("/home/pranjal/Downloads/free-resume-template-sand.jpg"),
]

# At least 12 diverse PDFs across categories (files that exist in dataset)
PDF_SAMPLES = [
    "resume_001_it_experienced.pdf",
    "resume_002_creative.pdf",
    "resume_003_it_experienced.pdf",
    "resume_004_creative.pdf",
    "resume_005_non_it.pdf",
    "resume_006_non_it.pdf",
    "resume_007_it_fresher.pdf",
    "resume_009_it_experienced.pdf",
    "resume_010_it_fresher.pdf",
    "resume_012_creative.pdf",
    "resume_040_creative.pdf",
    "resume_060_it_experienced.pdf",
    "resume_080_creative.pdf",
]


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def norm_email(s):
    return (s or "").strip().lower()


def skill_overlap(expected, got):
    expected_set = {norm(s) for s in (expected or [])}
    got_text = got or ""
    got_set = {norm(s) for s in re.split(r"[\n,]+", got_text) if s.strip()}
    if not expected_set:
        return 1.0, []
    hits = [s for s in expected if any(norm(s) in g or g in norm(s) for g in got_set)]
    return len(hits) / len(expected_set), hits


def check_experience(gt_exp, rows):
    issues = []
    if not gt_exp:
        return issues
    if not rows:
        issues.append("no experience rows")
        return issues
    for job in gt_exp:
        title = norm(job.get("title"))
        company = norm(job.get("company"))
        matched = False
        for row in rows:
            rt = norm(row.get("job_title"))
            rc = norm(row.get("company"))
            if title and title in rt or rt in title:
                if company and (company in rc or rc in company):
                    matched = True
                    if not row.get("description"):
                        issues.append(f"missing desc: {job.get('title')}")
                    break
        if not matched:
            issues.append(f"missing job: {job.get('title')} @ {job.get('company')}")
    return issues


def check_education(gt_edu, rows):
    issues = []
    if not gt_edu:
        return issues
    if not rows:
        issues.append("no education rows")
        return issues
    for edu in gt_edu:
        degree = norm(edu.get("degree"))
        inst = norm(edu.get("institution"))
        matched = any(
            degree in norm(r.get("degree") or "") or norm(r.get("degree") or "") in degree
            for r in rows
        )
        if not matched:
            issues.append(f"missing degree: {edu.get('degree')[:40]}")
    return issues


def run_batch(env):
    gt_by_file = {}
    if GROUND_TRUTH.exists():
        for item in json.loads(GROUND_TRUTH.read_text()):
            gt_by_file[item["filename"]] = item

    Partner = env["res.partner"]
    results = []

    samples = []
    for fn in PDF_SAMPLES:
        path = DATASET / fn
        if path.exists():
            samples.append((fn, path, gt_by_file.get(fn)))
    for path in IMAGE_SAMPLES:
        if path.exists():
            samples.append((path.name, path, None))

    for label, path, gt in samples:
        row = {"file": label, "category": gt.get("category") if gt else "image", "issues": []}
        try:
            data = path.read_bytes()
            p = Partner.new({
                "resume_file": base64.b64encode(data),
                "resume_filename": path.name,
            })
            details, raw = p._resume_build_details_from_file()
            row["name"] = details.get("name") or details.get("resume_candidate_name")
            row["email"] = details.get("email")
            row["phone"] = details.get("phone")
            row["skills"] = details.get("skills")
            row["hobbies"] = details.get("hobbies")
            row["languages"] = details.get("languages")
            row["exp_count"] = len(details.get("experience_lines") or [])
            row["edu_count"] = len(details.get("education_lines") or [])
            row["summary_len"] = len(details.get("summary") or "")

            if gt:
                if norm(gt.get("name")) not in norm(row["name"] or ""):
                    row["issues"].append(f"name: got '{row['name']}' expected '{gt.get('name')}'")
                if norm_email(row["email"]) != norm_email(gt.get("email")):
                    row["issues"].append(f"email: got '{row['email']}' expected '{gt.get('email')}'")
                phone_digits = re.sub(r"\D", "", row["phone"] or "")
                gt_digits = re.sub(r"\D", "", gt.get("phone") or "")
                if gt_digits and gt_digits[-10:] not in phone_digits:
                    row["issues"].append(f"phone mismatch")
                ratio, _ = skill_overlap(gt.get("skills"), row["skills"])
                row["skill_ratio"] = round(ratio, 2)
                if ratio < 0.3:
                    row["issues"].append(f"skills low overlap ({ratio:.0%})")
                row["issues"].extend(check_experience(gt.get("experience"), details.get("experience_lines")))
                row["issues"].extend(check_education(gt.get("education"), details.get("education_lines")))
                if gt.get("hobbies"):
                    raw_lower = (raw or "").lower()
                    hobbies_in_source = bool(
                        re.search(r"\b(?:hobbies?|interests?)\s*[:\-]", raw_lower)
                        or any(
                            norm(h) in re.sub(r"[^a-z0-9]+", " ", raw_lower)
                            for h in gt["hobbies"]
                        )
                    )
                    if hobbies_in_source and not row["hobbies"]:
                        row["issues"].append("hobbies empty")
                    elif hobbies_in_source and row["hobbies"]:
                        gh = {norm(h) for h in gt["hobbies"]}
                        rh = {norm(h) for h in re.split(r"[\n,]+", row["hobbies"])}
                        if len(gh & rh) < min(1, len(gh)):
                            row["issues"].append("hobbies mismatch")
                if gt.get("languages") and not row["languages"]:
                    row["issues"].append("languages empty")
            else:
                if not row["name"]:
                    row["issues"].append("name empty")
                if row["exp_count"] < 1:
                    row["issues"].append("no experience")
        except Exception as exc:
            row["issues"].append(f"ERROR: {exc}")

        results.append(row)

    return results


if __name__ == "__main__":
    # When pasted into odoo shell: results = exec(open(...).read()) or import
    pass
