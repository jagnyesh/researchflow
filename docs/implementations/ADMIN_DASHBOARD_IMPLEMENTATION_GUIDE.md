# Admin Dashboard Enhancement - Implementation Guide

**Status:** Ready for implementation (Next Session)
**Prerequisites:** ✅ Backend infrastructure complete, ✅ Researcher Portal complete
**Estimated Time:** 2-3 hours

---

## Overview

This guide details the remaining work to add request tracking and data download functionality to the Admin Dashboard. The backend infrastructure and Researcher Portal are already complete and tested.

---

## What's Already Done ✅

### Backend Infrastructure (Commit: 096bfd6)
- ✅ **FileStorageService** (`app/services/file_storage.py`) - 320 lines
  - Local filesystem storage at `/data/deliveries/{request_id}/`
  - CSV generation, ZIP creation, file listing
  - Metadata file management

- ✅ **Download API Endpoints** (`app/api/research.py`)
  - `GET /research/{request_id}/delivery` - Delivery metadata
  - `GET /research/{request_id}/download` - Full ZIP package
  - `GET /research/{request_id}/download/{filename}` - Individual files

- ✅ **Agent Enhancements**
  - ExtractionAgent: Generates actual CSV files
  - DeliveryAgent: Saves metadata files, logs to DataDelivery table

- ✅ **Infrastructure**
  - `/data/deliveries/` directory created
  - `.gitignore` configured
  - Environment variables: `DATA_DELIVERY_PATH`, `MAX_DOWNLOAD_SIZE_MB`

### Researcher Portal (Commit: bda5419)
- ✅ Enhanced sidebar with status badges (🟢🟡🔵🔴)
- ✅ Cohort size and file count display
- ✅ Comprehensive download section (ZIP + individual files)
- ✅ QA summary display
- ✅ Helper functions: `get_status_badge()`, `check_delivery_status()`, `download_file()`

---

## What Needs to Be Done 🎯

### Task 1: Add Sidebar to Admin Dashboard

**File:** `app/web_ui/admin_dashboard.py` (928 lines)

**Current Structure:**
- Uses tab-based layout (5 tabs: Overview, Agent Metrics, Pending Approvals, Escalations, Analytics)
- Shows last 10 recent requests in Overview tab
- No sidebar currently

**Implementation Steps:**

1. **Add Helper Functions** (similar to Researcher Portal)
   ```python
   import httpx

   def get_status_badge(state: str) -> str:
       """Get colored status badge"""
       # Copy from researcher_portal.py lines 57-70

   def check_delivery_status(request_id: str) -> dict:
       """Check delivery status via API"""
       # Copy from researcher_portal.py lines 73-94

   def download_file(request_id: str, filename: str = None):
       """Download files via API"""
       # Copy from researcher_portal.py lines 97-121
   ```

2. **Replace Tab Layout with Sidebar + Main Area**

   **Before** (line ~145):
   ```python
   # Tabs
   tab1, tab2, tab3, tab4, tab5 = st.tabs([...])
   ```

   **After**:
   ```python
   # Create columns: sidebar + main
   col_sidebar, col_main = st.columns([1, 3])

   with col_sidebar:
       st.header("📋 All Requests")
       show_requests_sidebar()

   with col_main:
       # Keep existing tab structure
       tab1, tab2, tab3, tab4, tab5 = st.tabs([...])
       # ... existing tab content
   ```

3. **Implement Sidebar Function**
   ```python
   def show_requests_sidebar():
       """Show all submitted requests in sidebar"""
       # Get all requests
       requests = run_async(
           st.session_state.orchestrator.get_all_active_requests()
       )

       # Add search/filter
       st.text_input("🔍 Search", key="search_requests")

       # Status filter
       status_filter = st.multiselect(
           "Filter by Status",
           ["delivered", "complete", "in_progress", "failed"],
           default=[]
       )

       # Display requests
       for req in requests:
           badge = get_status_badge(req["current_state"])

           with st.expander(f"{badge} {req['id'][:8]}..."):
               st.write(f"**Researcher:** {req['researcher_name']}")
               st.write(f"**Status:** {req['current_state']}")
               st.write(f"**Started:** {req['created_at'][:19]}")

               # Check delivery
               delivery = check_delivery_status(req['id'])
               if delivery.get("delivered"):
                   st.write(f"**Cohort:** {delivery['cohort_size']} patients")
                   st.write(f"**Files:** {len(delivery['files'])} ready")

               if st.button("View Details", key=f"view_{req['id']}"):
                   st.session_state.selected_request = req['id']
                   # Trigger modal (see Task 2)
   ```

---

### Task 2: Add Request Details Modal

**Approach:** Use `@st.dialog` decorator (Streamlit 1.27+)

**Implementation:**

1. **Create Modal Function**
   ```python
   @st.dialog("Request Details")
   def show_request_details_modal(request_id: str):
       """Show detailed request information in modal"""

       # Get request status
       status = run_async(
           st.session_state.orchestrator.get_request_status(request_id)
       )

       if not status:
           st.error(f"Request not found: {request_id}")
           return

       # Header
       st.subheader(f"Request: {request_id}")

       # Metrics
       col1, col2, col3 = st.columns(3)
       with col1:
           st.metric("Status", status["current_state"])
       with col2:
           st.metric("Current Agent", status.get("current_agent", "None"))
       with col3:
           started = datetime.fromisoformat(status["started_at"])
           duration = datetime.now() - started
           st.metric("Duration", f"{duration.seconds // 60} min")

       # Researcher Info
       st.markdown("### 👤 Researcher")
       researcher = status.get("researcher_info", {})
       st.write(f"**Name:** {researcher.get('name', 'N/A')}")
       st.write(f"**Email:** {researcher.get('email', 'N/A')}")
       st.write(f"**IRB:** {researcher.get('irb_number', 'N/A')}")

       # Workflow Timeline
       st.markdown("### 📊 Workflow Timeline")
       if status.get("agents_involved"):
           for activity in reversed(status["agents_involved"]):
               agent = activity["agent"].replace("_", " ").title()
               task = activity["task"].replace("_", " ").title()
               timestamp = activity["timestamp"][:19]
               st.markdown(f"**{timestamp}** - {agent}: {task}")

       # Approval History
       st.markdown("### ✅ Approval History")
       # Fetch from Approval table (need to add async query)
       # Show: Requirements Review, SQL Review, Extraction Approval, QA Review
       # with timestamps and reviewer names

       # Download Section (see Task 3)
       show_download_section(request_id)
   ```

2. **Trigger Modal from Sidebar**
   ```python
   # In show_requests_sidebar(), after "View Details" button:
   if st.button("View Details", key=f"view_{req['id']}"):
       st.session_state.selected_request = req['id']

   # At end of show_requests_sidebar():
   if "selected_request" in st.session_state:
       show_request_details_modal(st.session_state.selected_request)
       # Clear after modal closes
       if st.session_state.get("modal_closed"):
           del st.session_state.selected_request
   ```

---

### Task 3: Add Download Section to Modal

**Implementation:**

```python
def show_download_section(request_id: str):
    """Show download options in modal"""
    st.markdown("### 📦 Data Delivery")

    delivery_info = check_delivery_status(request_id)

    if delivery_info.get("delivered"):
        st.success("✅ Data ready for download")

        # Metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Cohort Size", f"{delivery_info.get('cohort_size', 0):,}")
        with col2:
            st.metric("Data Elements", len(delivery_info.get("data_elements", [])))
        with col3:
            st.metric("Files", len(delivery_info.get("files", [])))

        st.markdown("---")

        # Download ZIP
        st.markdown("**Download Complete Package (ZIP)**")
        if st.button("📦 Download ZIP", type="primary", use_container_width=True):
            with st.spinner("Preparing download..."):
                file_content, filename = download_file(request_id)
                if file_content:
                    st.download_button(
                        label="💾 Save ZIP",
                        data=file_content,
                        file_name=filename,
                        mime="application/zip",
                        type="primary",
                        use_container_width=True
                    )

        st.markdown("---")

        # Individual files
        st.markdown("**Individual Files**")
        files = delivery_info.get("files", [])
        for file_info in files:
            filename = file_info.get("filename", "unknown")
            size_mb = file_info.get("size_mb", 0)

            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"📄 {filename} ({size_mb:.2f} MB)")
            with col2:
                if st.button("Download", key=f"dl_admin_{filename}"):
                    file_content, _ = download_file(request_id, filename)
                    if file_content:
                        st.download_button(
                            label=f"💾 Save",
                            data=file_content,
                            file_name=filename,
                            mime="text/csv" if filename.endswith(".csv") else "text/plain",
                            key=f"save_admin_{filename}"
                        )

        # QA Summary
        if delivery_info.get("qa_report_summary"):
            st.markdown("---")
            st.markdown("**Quality Assurance Summary**")
            st.json(delivery_info["qa_report_summary"])

    else:
        st.info(f"Data not yet delivered. Current status: {delivery_info.get('current_state', 'N/A')}")
```

---

## Implementation Checklist

- [ ] Import httpx at top of admin_dashboard.py
- [ ] Add helper functions: `get_status_badge()`, `check_delivery_status()`, `download_file()`
- [ ] Replace tab-only layout with sidebar + tab layout
- [ ] Implement `show_requests_sidebar()` function
- [ ] Add search/filter functionality to sidebar
- [ ] Create `show_request_details_modal()` with `@st.dialog`
- [ ] Add approval history section to modal
- [ ] Implement `show_download_section()` in modal
- [ ] Test modal open/close behavior
- [ ] Test download functionality for informaticians
- [ ] Add environment variable: `API_BASE_URL` (default: http://localhost:8000)

---

## Testing Steps

1. **Backend Test:**
   ```bash
   # Start API server
   uvicorn app.main:app --reload --port 8000

   # Test delivery endpoint
   curl http://localhost:8000/research/REQ-20250104-ABC123/delivery

   # Test download endpoint
   curl -O http://localhost:8000/research/REQ-20250104-ABC123/download
   ```

2. **UI Test:**
   ```bash
   # Start Admin Dashboard
   streamlit run app/web_ui/admin_dashboard.py --server.port 8502

   # Test checklist:
   # - [ ] Sidebar shows all requests with badges
   # - [ ] Clicking "View Details" opens modal
   # - [ ] Modal shows complete request info
   # - [ ] Download ZIP button works
   # - [ ] Individual file download works
   # - [ ] QA summary displays correctly
   # - [ ] Modal closes properly
   ```

3. **End-to-End Test:**
   ```bash
   # 1. Submit request via Researcher Portal (port 8501)
   # 2. Approve via Admin Dashboard (port 8502)
   # 3. Wait for delivery
   # 4. Verify download in both portals
   # 5. Check files in /data/deliveries/{request_id}/
   ```

---

## Code Reuse Strategy

**Copy from Researcher Portal:**
- `get_status_badge()` - lines 57-70
- `check_delivery_status()` - lines 73-94
- `download_file()` - lines 97-121
- Download section logic - lines 465-556

**Adapt for Admin Dashboard:**
- Show ALL requests (not just user's requests)
- Add informatician-specific features (approval history)
- Use modal instead of tab for request details
- Add search/filter for large request lists

---

## Key Differences from Researcher Portal

| Feature | Researcher Portal | Admin Dashboard |
|---------|------------------|----------------|
| Request List | User's requests only | All requests |
| Layout | Sidebar + 2 tabs | Sidebar + 5 tabs |
| Details View | Dedicated tab | Modal popup |
| Download Access | Researcher only | Informatician review |
| Additional Info | N/A | Approval history, all researcher info |

---

## Environment Variables

Add to `.env` if not present:
```bash
# API base URL for download endpoints
API_BASE_URL=http://localhost:8000

# Data delivery storage path
DATA_DELIVERY_PATH=/data/deliveries

# Maximum download size
MAX_DOWNLOAD_SIZE_MB=500
```

---

## Files to Modify

1. **`app/web_ui/admin_dashboard.py`** (MAIN)
   - Add imports: `httpx`
   - Add helper functions
   - Modify layout: Add sidebar column
   - Add `show_requests_sidebar()`
   - Add `show_request_details_modal()` with `@st.dialog`
   - Add `show_download_section()`

2. **`config/.env.example`** (if needed)
   - Add `API_BASE_URL` if not present

---

## Success Criteria

✅ Admin Dashboard has left sidebar with ALL submitted requests
✅ Sidebar shows status badges and delivery info
✅ Clicking request opens modal with full details
✅ Modal shows approval history timeline
✅ Download button works for ZIP package
✅ Individual file downloads work
✅ QA summary displayed in modal
✅ Modal closes properly after viewing
✅ Search/filter functionality works
✅ No errors in console or logs

---

## Estimated LOC Changes

- Imports: +2 lines
- Helper functions: +60 lines
- Layout modification: +20 lines
- Sidebar function: +80 lines
- Modal function: +150 lines
- Download section: +120 lines

**Total:** ~430 new lines in admin_dashboard.py

---

## Next Steps After Implementation

1. **Testing:**
   - Unit tests for helper functions
   - Integration tests for download flow
   - UI testing for modal behavior

2. **Documentation:**
   - Update README with download instructions
   - Add screenshots to docs
   - Update user guide

3. **Optional Enhancements:**
   - Real-time status updates (WebSocket)
   - Batch download (multiple requests)
   - Email notifications when data ready
   - Export request list to CSV
   - Advanced filtering (date range, researcher, status)

---

## Reference Links

- **Backend Commit:** 096bfd6 (File storage infrastructure)
- **Researcher Portal Commit:** bda5419 (Download functionality)
- **API Endpoints:** `/research/{request_id}/delivery`, `/download`, `/download/{filename}`
- **File Storage:** `/data/deliveries/{request_id}/`
- **Database Table:** `DataDelivery` (stores file_list, cohort_size, delivery_location)

---

## Questions to Consider

1. Should informaticians see a "download history" (who downloaded what, when)?
2. Should there be a "mark as reviewed" button after informatician downloads?
3. Should expired data (>90 days) be automatically deleted from `/data/deliveries/`?
4. Should there be audit logging for download events?

---

**Status:** Ready for implementation
**Last Updated:** 2025-01-04
**Next Session:** Admin Dashboard Enhancement
