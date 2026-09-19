# 📘 CBE Reports – Student Performance & Fee Management

A FastAPI backend for generating **student performance reports** and **fee summaries**.  
This tool helps teachers and administrators manage marks, fee payments, balances, and automatically generate individual reports and a consolidated PDF booklet.

---

## 🚀 Features
- Upload **performance** and **fees** data (CSV or JSON).
- Merge datasets to produce a unified student record.
- Automatically calculate:
  - Subject totals
  - Overall score
  - Fee paid and balance
  - Student status 
- Generate:
  - Individual text reports per student
  - A consolidated PDF booklet with all student reports
  - Summary statistics (averages, totals, at-risk count)
- API endpoints for both **CSV upload** and **direct JSON entry** (teachers can key in marks & fees via frontend).

---

## ⚙️ Installation & Setup

1. Clone the repository:
   ```bash
   git clone git@github.com:Natiri-Spencer/CBE-Reports.git
   cd CBE-Reports/student_reports_backend

## 🛠️ Tech Stack

- **FastAPI** → Modern Python web framework for building APIs  
- **Pandas** → Data analysis and manipulation (merging CSVs, calculating averages)  
- **NumPy** → Numerical computations and array operations  
- **ReportLab** → PDF generation for student report booklets  
- **CSV / JSON** → Supported input formats for student performance and fee data  
- **Python 3.10+** → Core programming language powering the backend  
- **Git & GitHub** → Version control and collaboration  


