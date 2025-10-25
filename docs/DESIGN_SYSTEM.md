# ResearchFlow Design System

**Version**: 1.0
**Last Updated**: 2025-10-23
**Status**: ✅ Implemented across all three apps

## Overview

ResearchFlow uses a unified design system built on **glass morphism** aesthetics, providing a modern, professional, and consistent user experience across the Researcher Portal, Admin Dashboard, and Research Notebook.

## Core Principles

1. **Healthcare Context**: Professional, credible, trustworthy (not playful)
2. **Information Density**: Show data clearly without overwhelming
3. **Speed**: Fast interactions, minimal unnecessary animations
4. **Accessibility**: WCAG AA compliant, fully keyboard navigable
5. **Consistency**: Same patterns across all three applications

---

## Color Palette

### Primary Colors
- **Primary Blue**: `#007AFF` - Actions, links, primary buttons
- **Primary Hover**: `#0051D5` - Hover states
- **Primary Light**: `rgba(0, 122, 255, 0.1)` - Subtle backgrounds

### Secondary Colors
- **Secondary Purple**: `#5856D6` - Secondary actions
- **Secondary Light**: `rgba(88, 86, 214, 0.1)` - Backgrounds

### Status Colors
| Status | Color | Usage |
|--------|-------|-------|
| ✅ Success | `#28a745` | Approved, completed states |
| ⚠️ Warning | `#ffc107` | Pending, needs attention |
| ❌ Danger | `#dc3545` | Rejected, errors, critical alerts |
| ℹ️ Info | `#17a2b8` | Informational messages |

### Text Colors
- **Primary Text**: `#1d1d1f` - Body text, headings
- **Secondary Text**: `#86868b` - Captions, placeholders
- **Inverse Text**: `#ffffff` - Text on dark backgrounds

### Neutral Grays
- Gray 50-800 scale from `#f5f7fa` to `#111827`
- Used for borders, backgrounds, disabled states

### Backgrounds
- **Gradient Start**: `#f5f7fa`
- **Gradient End**: `#e8ecf1`
- **Glass Effect**: `rgba(255, 255, 255, 0.7)` with `backdrop-filter: blur(20px)`
- **Glass Elevated**: `rgba(255, 255, 255, 0.85)` for cards requiring more emphasis

---

## Typography

### Font Families
```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
font-family-mono: "SF Mono", "Roboto Mono", "Courier New", monospace;
```

### Font Scale
| Size | Rem | Pixels | Usage |
|------|-----|--------|-------|
| XS | 0.75rem | 12px | Badges, tiny labels |
| SM | 0.875rem | 14px | Captions, small text |
| Base | 1rem | 16px | Body text (minimum) |
| LG | 1.125rem | 18px | Emphasized text |
| XL | 1.25rem | 20px | Subheadings |
| 2XL | 1.5rem | 24px | H3 |
| 3XL | 1.875rem | 30px | H1, H2 |

### Font Weights
- **Normal**: 400 - Body text
- **Medium**: 500 - Labels, nav items
- **Semibold**: 600 - Headings, emphasis
- **Bold**: 700 - Critical alerts, strong emphasis

---

## Spacing System

Based on **8px grid system**:

| Token | Value | Pixels | Usage |
|-------|-------|--------|-------|
| XS | 0.25rem | 4px | Tight spacing |
| SM | 0.5rem | 8px | Small gaps |
| MD | 1rem | 16px | Default spacing |
| LG | 1.5rem | 24px | Section spacing |
| XL | 2rem | 32px | Large sections |
| 2XL | 3rem | 48px | Major sections |
| 3XL | 4rem | 64px | Page sections |

---

## Border Radius

| Token | Value | Pixels | Usage |
|-------|-------|--------|-------|
| SM | 0.375rem | 6px | Small elements |
| MD | 0.5rem | 8px | Badges, tags |
| LG | 0.75rem | 12px | Buttons, inputs |
| XL | 1rem | 16px | Cards |
| 2XL | 1.25rem | 20px | Large cards, chat bubbles |
| Full | 9999px | Circle | Pills, rounded buttons |

---

## Shadows

```css
/* Elevation levels */
sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05)          /* Subtle lift */
md: 0 4px 6px -1px rgba(0, 0, 0, 0.1)        /* Cards */
lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1)      /* Elevated cards */
xl: 0 20px 25px -5px rgba(0, 0, 0, 0.1)      /* Modals, popovers */
glass: 0 8px 32px 0 rgba(31, 38, 135, 0.15)  /* Glass morphism */
primary: 0 4px 15px rgba(0, 122, 255, 0.3)   /* Primary buttons */
```

---

## Components

### Buttons

**Primary Button**
```html
<button class="stButton">Submit</button>
```
- Background: `#007AFF`
- Hover: Lift effect (`translateY(-2px)`) + darker blue
- Shadow: Primary blue glow
- Border radius: `12px`

**Secondary Button**
```html
<button class="stButton secondary">Cancel</button>
```
- Background: `rgba(0, 0, 0, 0.05)`
- Minimal shadow
- Gray text

**Danger Button**
```html
<button class="stButton danger">Delete</button>
```
- Background: `#dc3545`
- Red shadow glow
- Use sparingly

### Chat Messages

**User Message** (right-aligned, blue)
```html
<div class="user-message">
  I need heart failure patients from 2024...
</div>
```
- Background: `rgba(0, 122, 255, 0.9)`
- White text
- 20px border radius
- Slide-in animation

**Assistant Message** (left-aligned, white)
```html
<div class="assistant-message">
  I can help with that. Let me clarify a few details...
</div>
```
- Background: `rgba(255, 255, 255, 0.9)`
- Dark text
- Glass effect

### Status Badges

```html
<span class="status-badge status-pending">Pending</span>
<span class="status-badge status-approved">Approved</span>
<span class="status-badge status-rejected">Rejected</span>
<span class="status-badge status-critical">CRITICAL</span>
```

| Status | Background | Text | Border | Special |
|--------|-----------|------|--------|---------|
| Pending | `#fff3cd` | `#856404` | `#ffc107` | - |
| Approved | `#d4edda` | `#155724` | `#28a745` | - |
| Rejected | `#f8d7da` | `#721c24` | `#dc3545` | - |
| Critical | `#dc3545` | `white` | `#a71d2a` | Pulse animation |

### Glass Cards

```html
<div class="glass-card">
  <!-- Content -->
</div>
```
- Background: `rgba(255, 255, 255, 0.7)`
- Backdrop blur: `20px`
- Border: `1px solid rgba(255, 255, 255, 0.5)`
- Shadow: Glass effect

**Elevated variant** (more emphasis):
```html
<div class="glass-card-elevated">
  <!-- Content -->
</div>
```

### Input Fields

- Background: `rgba(255, 255, 255, 0.95)`
- Focus: Blue border + subtle blue shadow
- Placeholder: Gray (`#86868b`)
- Border radius: `12px`
- Padding: `16px`

### Data Tables

- Header: Light blue background (`rgba(0, 122, 255, 0.1)`)
- Hover: Slight background change
- Border radius: `12px`
- Glass effect background

---

## Animations

### Timing
- Fast: `0.15s` - Micro-interactions
- Normal: `0.2s` - Standard transitions
- Slow: `0.3s` - Large state changes

### Easing
- **ease**: Default for most transitions
- **ease-out**: Entrances (chat messages, modals)
- **ease-in-out**: Hover states

### Slide In Animations
```css
@keyframes slideInRight {
  from { opacity: 0; transform: translateX(20px); }
  to { opacity: 1; transform: translateX(0); }
}

@keyframes slideInLeft {
  from { opacity: 0; transform: translateX(-20px); }
  to { opacity: 1; transform: translateX(0); }
}
```

### Pulse Animation (Critical Badge)
```css
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.8; }
}
```

### Reduced Motion
```css
@media (prefers-reduced-motion: reduce) {
  * {
    animation: none !important;
    transition: none !important;
  }
}
```

---

## Accessibility

### WCAG AA Compliance

✅ **Color Contrast**:
- Primary blue on white: 4.5:1 (AA)
- Text on backgrounds: minimum 4.5:1
- Large text: minimum 3:1

✅ **Keyboard Navigation**:
- All buttons focusable
- Tab order logical
- Enter to submit forms
- Escape to close modals

✅ **Screen Readers**:
- Semantic HTML
- ARIA labels where needed
- Alt text on images/icons
- Status announcements

✅ **Focus States**:
- Visible blue outline on focus
- Not removed with CSS

---

## App-Specific Notes

### Researcher Portal (Port 8501)
- Focus: Conversational UI, friendly tone
- Key components: Chat bubbles, progress indicators, review cards
- Special: Chat animations, completion celebrations

### Admin Dashboard (Port 8502)
- Focus: Information density, decision-making
- Key components: Data tables, approval cards, metrics
- Special: **CRITICAL SQL alerts**, urgency indicators, validation checklists

### Research Notebook (Port 8503)
- Focus: Interactive analysis, data visualization
- Key components: Chat interface, feasibility cards, charts
- Special: Intent detection, feasibility result displays

---

## App Navigation

All three apps include a unified navigation header:

```
ResearchFlow | 🔬 Researcher Portal | ⚙️ Admin Dashboard | 🤖 Research Notebook
```

- Links open in new tabs
- Current app not clickable
- Hover states with subtle background
- Fixed at top of page

---

## Implementation

### Importing the Design System

```python
from app.web_ui.shared.design_system import (
    get_base_styles,
    render_status_badge,
    render_metric_card,
    render_critical_alert,
    get_app_navigation_header
)

# Apply base styles
st.markdown(get_base_styles(), unsafe_allow_html=True)

# Add navigation header
st.markdown(get_app_navigation_header(), unsafe_allow_html=True)

# Render components
st.markdown(render_status_badge("pending"), unsafe_allow_html=True)
st.markdown(render_critical_alert("SQL Review", "Check query"), unsafe_allow_html=True)
```

### File Locations

- **Design System**: `app/web_ui/shared/design_system.py`
- **Researcher Portal**: `app/web_ui/researcher_portal.py`
- **Admin Dashboard**: `app/web_ui/admin_dashboard.py`
- **Research Notebook**: `app/web_ui/research_notebook.py`

---

## Component Gallery

### Status Badges
![Pending Badge](#) **Pending** - Yellow background, dark yellow text
![Approved Badge](#) **Approved** - Green background, dark green text
![Rejected Badge](#) **Rejected** - Red background, dark red text
![Critical Badge](#) **CRITICAL** - Red with pulse animation

### Buttons
![Primary Button](#) **Submit** - Blue with hover lift
![Secondary Button](#) **Cancel** - Gray, minimal
![Danger Button](#) **Delete** - Red with glow

### Cards
![Glass Card](#) Standard card with blur effect
![Glass Elevated](#) Elevated card for emphasis
![Critical Alert](#) Red alert box with pulsing badge

---

## Do's and Don'ts

### ✅ Do's
- Use the shared design system for all new components
- Maintain consistent spacing with the 8px grid
- Use semantic color meanings (green = success, red = danger)
- Test with keyboard navigation
- Check color contrast for accessibility
- Add animations sparingly and respect `prefers-reduced-motion`

### ❌ Don'ts
- Don't create one-off colors not in the palette
- Don't use inline styles when a component exists
- Don't remove focus outlines for accessibility
- Don't animate critical UI elements
- Don't use red for anything except danger/critical
- Don't create duplicate CSS in individual app files

---

## Future Enhancements

### Phase 2 (Planned)
- [ ] Dark mode support
- [ ] Interactive component gallery (Storybook-style)
- [ ] Custom Streamlit theme config (`.streamlit/config.toml`)
- [ ] Plotly charts with design system colors
- [ ] Toast notification system
- [ ] Modal/dialog components

### Phase 3 (Planned)
- [ ] Skeleton loaders for loading states
- [ ] Micro-interactions (button ripples, etc.)
- [ ] Onboarding tour system
- [ ] Keyboard shortcuts overlay
- [ ] Visual regression tests with Playwright

---

## Version History

### v1.0 (2025-10-23)
- ✅ Initial design system created
- ✅ Applied to all three Streamlit apps
- ✅ Shared component library (`design_system.py`)
- ✅ Unified color palette, typography, spacing
- ✅ Glass morphism styling
- ✅ App navigation header
- ✅ **CRITICAL** SQL approval UI improvements
- ✅ Accessibility features (keyboard nav, focus states)
- ✅ Reduced ~600 lines of duplicate CSS across apps

---

## Support & Feedback

For questions or suggestions about the design system:
- Open an issue in the GitHub repo
- Tag with `design-system` label
- Include screenshots if reporting visual bugs

---

**Last Updated**: October 23, 2025
**Maintained By**: ResearchFlow Team
