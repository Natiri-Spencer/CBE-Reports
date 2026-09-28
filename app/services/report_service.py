# app/services/report_service.py
import os
import pandas as pd
import numpy as np
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.models.schemas import ReportSummary, FeeSummary, StudentFeeRecord

_last_summary = None  # cache last summary


def calculate_fee_balances(df: pd.DataFrame, fee_per_term: int = 10000):
    """
    Calculate fee balances for each learner.
    Admin-only logic: Fee Balance = fee_per_term - Fee Paid (min 0).
    """
    if "Fee Paid" not in df.columns:
        raise ValueError("Missing 'Fee Paid' column in dataset")

    df["Fee Balance"] = np.where(df["Fee Paid"] >= fee_per_term,
                                 0,
                                 fee_per_term - df["Fee Paid"])
    return df


def compute_reports(df: pd.DataFrame):
    """
    Shared logic: compute totals, status, per-student records, and per-grade summaries.
    """
    subject_cols = [c for c in df.columns if c not in ["Learner Name", "Grade", "Fee Paid",
                                                       "Fee Balance", "TOTAL", "Status"]]

    # Compute totals and status
    df["TOTAL"] = df[subject_cols].sum(axis=1)
    df = calculate_fee_balances(df)  # ensure balances are calculated
    df["Status"] = np.where((df["TOTAL"] < 550) | (df["Fee Balance"] > 0),
                            "At Risk", "Good Standing")

    # Per-grade summary
    grade_summary = df.groupby("Grade").agg({
        "TOTAL": "mean",
        "Fee Paid": "sum",
        "Fee Balance": "sum",
        "Learner Name": "count"
    }).reset_index()

    return df, grade_summary, subject_cols


def generate_pdf_booklet(combined_df, subject_cols, output_file="Student_Report_Booklet.pdf"):
    """
    Generate a PDF booklet with per-student pages and a summary page.
    """
    c = canvas.Canvas(output_file, pagesize=A4)
    width, height = A4

    for _, row in combined_df.iterrows():
        learner_name = row["Learner Name"]

        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height - 50, f"📘 Student Report: {learner_name}")

        c.setFont("Helvetica", 12)
        y = height - 80

        for subj in subject_cols:
            c.drawString(50, y, f"{subj}: {row[subj]}")
            y -= 20

        c.drawString(50, y, f"TOTAL Marks: {row['TOTAL']}"); y -= 20
        c.drawString(50, y, f"Fee Paid: {row['Fee Paid']} KES"); y -= 20
        c.drawString(50, y, f"Fee Balance: {row['Fee Balance']} KES"); y -= 20
        c.drawString(50, y, f"Status: {row['Status']}")

        c.showPage()

    # Summary page
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "📊 Summary Report")

    c.setFont("Helvetica", 12)
    y = height - 80

    total_collected = combined_df["Fee Paid"].sum()
    total_balance = combined_df["Fee Balance"].sum()
    avg_score = combined_df["TOTAL"].mean()
    num_at_risk = (combined_df["Status"] == "At Risk").sum()

    c.drawString(50, y, f"Total Fees Collected: {round(total_collected,2)} KES"); y -= 20
    c.drawString(50, y, f"Total Outstanding Balance: {round(total_balance,2)} KES"); y -= 20
    c.drawString(50, y, f"Average Total Score: {round(avg_score,2)}"); y -= 20
    c.drawString(50, y, f"Number of Students At Risk: {num_at_risk}"); y -= 40

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Subject Averages:"); y -= 20
    c.setFont("Helvetica", 12)
    for subj in subject_cols:
        avg_subj = combined_df[subj].mean()
        c.drawString(50, y, f"{subj}: {round(avg_subj,2)}")
        y -= 20

    c.showPage()
    c.save()
    return output_file


def generate_reports(performance_file, fees_file):
    """
    Service wrapper: generate text reports, PDF booklet, and summary stats.
    Returns per-student records, per-grade summaries, and ReportSummary.
    """
    performance_df = pd.read_csv(performance_file)
    fees_df = pd.read_csv(fees_file)

    combined_df = performance_df.merge(fees_df, on="Learner Name", how="inner")
    combined_df, grade_summary, subject_cols = compute_reports(combined_df)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_file = f"Student_Report_Booklet_{timestamp}.pdf"
    generate_pdf_booklet(combined_df, subject_cols, output_file=pdf_file)

    subject_averages = {subj: round(float(combined_df[subj].mean()), 2) for subj in subject_cols}

    global _last_summary
    _last_summary = ReportSummary(
        total_students=len(combined_df),
        at_risk=int((combined_df["Status"] == "At Risk").sum()),
        avg_score=round(float(combined_df["TOTAL"].mean()), 2),
        total_fees=round(float(combined_df["Fee Paid"].sum()), 2),
        total_balance=round(float(combined_df["Fee Balance"].sum()), 2),
        subject_averages=subject_averages,
        pdf_path=pdf_file
    )

    return {
        "students": combined_df.to_dict(orient="records"),
        "grade_summary": grade_summary.to_dict(orient="records"),
        "summary": _last_summary
    }


def get_last_summary():
    return _last_summary


def generate_fee_summary(file) -> FeeSummary:
    """
    Admin-only: generate fee summary from uploaded file.
    """
    df = pd.read_csv(file)
    df = calculate_fee_balances(df)

    students = [
        StudentFeeRecord(
            learner_name=row["Learner Name"],
            fee_paid=float(row["Fee Paid"]),
            fee_balance=float(row["Fee Balance"])
        )
        for _, row in df.iterrows()
    ]

    return FeeSummary(
        total_fees=float(df["Fee Paid"].sum()),
        total_balance=float(df["Fee Balance"].sum()),
        students=students
    )
# Service functions for grading and comments

def grade_comment(score: int) -> str:
    if 0 <= score <= 9:
        return "BE2"
    elif 10 <= score <= 19:
        return "BE1"
    elif 20 <= score <= 29:
        return "AE2"
    elif 30 <= score <= 42:
        return "AE1"
    elif 43 <= score <= 56:
        return "ME2"
    elif 57 <= score <= 74:
        return "ME1"
    elif 75 <= score <= 89:
        return "EE2"
    elif 90 <= score <= 100:
        return "EE1"
    else:
        return "Invalid"
