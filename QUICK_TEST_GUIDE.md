# Quick Test Guide: Researcher Portal Sidebar Fix

**⏱️ Estimated Time**: 5-10 minutes

---

## 🚀 Quick Start (3 Commands)

```bash
# 1. Install the new cookie library
pip install extra-streamlit-components==0.1.71

# 2. Start Researcher Portal
streamlit run app/web_ui/researcher_portal.py --server.port 8501

# 3. (In a new terminal) Start Admin Dashboard
streamlit run app/web_ui/admin_dashboard.py --server.port 8502
```

---

## ✅ Test 1: Researcher Portal Sidebar Persistence (2 minutes)

### The Bug You Reported
> "The refresh button erases the past requests made. This is a bug."

### How to Verify It's Fixed

1. **Open Researcher Portal**: http://localhost:8501

2. **Enter Your Email** in the sidebar (e.g., test@example.com)

3. **See Your Requests Load** automatically from database

4. **Refresh the Page** (Press F5)

5. **✅ Verify**:
   - ✅ Email is still filled in (from cookie)
   - ✅ Requests are still visible (from database)
   - ✅ **BUG FIXED!** 🎉

---

## ✅ Test 2: Admin Dashboard Approval History

1. **Open Admin Dashboard**: http://localhost:8502

2. **Click any request** in sidebar → Modal opens

3. **Look for "✅ Approval History" section**

4. **✅ Verify**: Section exists between workflow and download sections

---

**Full documentation**: See `IMPLEMENTATION_SUMMARY.md`
