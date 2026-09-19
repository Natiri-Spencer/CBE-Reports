import pandas as pd
import numpy as np
import math
from app.models.schemas import ReportSummary
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import os
from datetime import datetime

_last_summary = None  # cache last summary


def generate_individual_reports(performance_file, fees_file, output_folder="reports"):
    try:
        os.makedirs(output_folder, exist_ok=True)

        performance_df = pd.read_csv(performance_file)
        fees_df = pd.read_csv(fees_file)

        combined_df = performance_df.merge(fees_df, on="Learner Name", how="inner")
        combined_df["Status"] = np.where(
            (combined_df["TOTAL"] < 550) | (combined_df["Fee Balance"] > 0),
            "At Risk",
            "Good Standing"
        )

        subject_cols = [col for col in performance_df.columns if col not in ["Learner Name", "TOTAL"]]

        for _, row in combined_df.iterrows():
            learner_name = row["Learner Name"]
            safe_name = learner_name.replace(" ", "_").upper()
            file_path = f"{output_folder}/{safe_name}_report.txt"

            subject_marks = "\n".join([f"{subj}: {row[subj]}" for subj in subject_cols])

            report_text = (
                f"📘 Student Report: {learner_name}\n"
                f"---------------------------------\n"
                f"{subject_marks}\n"
                f"TOTAL Marks: {row['TOTAL']}\n"
                f"Fee Paid: {row['Fee Paid']} KES\n"
                f"Fee Balance: {row['Fee Balance']} KES\n"
                f"Status: {row['Status']}\n"
            )

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(report_text)

        return combined_df
    except Exception as e:
        print("❌ Error in generate_individual_reports:", e)
        raise


def generate_pdf_booklet(combined_df, output_file="Student_Report_Booklet.pdf"):
    try:
        subject_cols = [col for col in combined_df.columns if col not in ["Learner Name", "TOTAL", "Fee Paid", "Fee Balance", "Status"]]

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
        print(f"✅ PDF booklet saved to {output_file}")

        return combined_df
    except Exception as e:
        print("❌ Error in generate_pdf_booklet:", e)
        raise


def generate_reports(performance_file, fees_file):
    """
    Service wrapper: generate text reports, PDF booklet, and summary stats.
    """
    print("➡️ Starting report generation...")

    try:
        combined_df = generate_individual_reports(performance_file, fees_file)
        print("✅ Individual reports generated. Columns:", combined_df.columns.tolist())

        # Dynamic PDF filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_file = f"Student_Report_Booklet_{timestamp}.pdf"
        generate_pdf_booklet(combined_df, output_file=pdf_file)
        print("✅ PDF booklet generated at:", pdf_file)

        subject_cols = [col for col in combined_df.columns if col not in ["Learner Name", "TOTAL", "Fee Paid", "Fee Balance", "Status"]]
        print("📊 Subject columns identified:", subject_cols)

        subject_averages = {}
        for subj in subject_cols:
            mean_val = combined_df[subj].mean()
            subject_averages[subj] = round(float(mean_val), 2) if not math.isnan(mean_val) else 0.0
        print("📊 Subject averages calculated:", subject_averages)

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
        print("✅ ReportSummary built successfully:", _last_summary.dict())

        return _last_summary
    except Exception as e:
        print("❌ Error in generate_reports:", e)
        raise


def get_last_summary():
    return _last_summary
