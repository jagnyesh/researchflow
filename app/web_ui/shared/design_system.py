"""
ResearchFlow Design System

Unified design tokens, CSS styles, and reusable components for all Streamlit apps.
Provides consistency across Researcher Portal, Admin Dashboard, and Research Notebook.
"""

# ============================================================================
# DESIGN TOKENS
# ============================================================================

# Color Palette
COLORS = {
    # Primary (Actions, Links)
    'primary': '#007AFF',
    'primary_hover': '#0051D5',
    'primary_light': 'rgba(0, 122, 255, 0.1)',

    # Secondary
    'secondary': '#5856D6',
    'secondary_light': 'rgba(88, 86, 214, 0.1)',

    # Status Colors
    'success': '#28a745',
    'success_light': '#d4edda',
    'warning': '#ffc107',
    'warning_light': '#fff3cd',
    'danger': '#dc3545',
    'danger_light': '#f8d7da',
    'info': '#17a2b8',
    'info_light': '#d1ecf1',

    # Neutral Grays
    'gray_50': '#f5f7fa',
    'gray_100': '#e8ecf1',
    'gray_200': '#d1d5db',
    'gray_300': '#9ca3af',
    'gray_400': '#6b7280',
    'gray_500': '#4b5563',
    'gray_600': '#374151',
    'gray_700': '#1f2937',
    'gray_800': '#111827',

    # Text
    'text_primary': '#1d1d1f',
    'text_secondary': '#86868b',
    'text_inverse': '#ffffff',

    # Backgrounds
    'bg_gradient_start': '#f5f7fa',
    'bg_gradient_end': '#e8ecf1',
    'bg_glass': 'rgba(255, 255, 255, 0.7)',
    'bg_glass_elevated': 'rgba(255, 255, 255, 0.85)',
    'bg_sidebar': 'rgba(255, 255, 255, 0.6)',
}

# Typography Scale
TYPOGRAPHY = {
    'font_family': '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    'font_family_mono': '"SF Mono", "Roboto Mono", "Courier New", monospace',

    # Font Sizes
    'text_xs': '0.75rem',    # 12px
    'text_sm': '0.875rem',   # 14px
    'text_base': '1rem',     # 16px
    'text_lg': '1.125rem',   # 18px
    'text_xl': '1.25rem',    # 20px
    'text_2xl': '1.5rem',    # 24px
    'text_3xl': '1.875rem',  # 30px

    # Font Weights
    'weight_normal': '400',
    'weight_medium': '500',
    'weight_semibold': '600',
    'weight_bold': '700',
}

# Spacing System (8px grid)
SPACING = {
    'xs': '0.25rem',   # 4px
    'sm': '0.5rem',    # 8px
    'md': '1rem',      # 16px
    'lg': '1.5rem',    # 24px
    'xl': '2rem',      # 32px
    '2xl': '3rem',     # 48px
    '3xl': '4rem',     # 64px
}

# Border Radius
RADIUS = {
    'sm': '0.375rem',   # 6px
    'md': '0.5rem',     # 8px
    'lg': '0.75rem',    # 12px
    'xl': '1rem',       # 16px
    '2xl': '1.25rem',   # 20px
    'full': '9999px',
}

# Shadows
SHADOWS = {
    'sm': '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
    'md': '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
    'lg': '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
    'xl': '0 20px 25px -5px rgba(0, 0, 0, 0.1)',
    'glass': '0 8px 32px 0 rgba(31, 38, 135, 0.15)',
    'primary': '0 4px 15px rgba(0, 122, 255, 0.3)',
}


# ============================================================================
# BASE STYLES
# ============================================================================

def get_base_styles() -> str:
    """
    Returns complete CSS stylesheet with design system applied.
    Include this in all Streamlit apps via st.markdown()
    """
    return f"""
    <style>
        /* ===== FORCE LIGHT THEME - AGGRESSIVE OVERRIDES ===== */

        /* Main app containers */
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stApp"],
        .main,
        .block-container,
        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        section[data-testid="stMain"] {{
            background-color: white !important;
            background: white !important;
            color: {COLORS['text_primary']} !important;
        }}

        /* Override Streamlit's default background */
        .main .block-container {{
            background: white !important;
        }}

        /* Force all divs and sections to white unless specifically styled */
        div[class*="css-"],
        section[class*="css-"] {{
            background-color: transparent !important;
        }}

        /* ===== CRITICAL: TARGET SIDEBAR AND MAIN CONTENT AREAS ===== */

        /* Sidebar - force light gray background */
        [data-testid="stSidebar"],
        [data-testid="stSidebarContent"],
        section[data-testid="stSidebar"],
        .css-1d391kg {{
            background-color: {COLORS['gray_50']} !important;
            background: {COLORS['gray_50']} !important;
        }}

        /* Main content area wrapper */
        section.main > div:first-child,
        section[data-testid="stMain"] > div:first-child,
        .stApp > div:not([data-testid="stSidebar"]) {{
            background: white !important;
        }}

        /* All direct children of stApp except sidebar */
        .stApp > div {{
            background: white !important;
        }}

        /* Chat input and its container */
        [data-testid="stBottom"],
        [data-testid="stChatInput"],
        [data-testid="stChatInput"] > div,
        .stChatFloatingInputContainer {{
            background-color: white !important;
            background: white !important;
        }}

        /* Target any remaining dark containers */
        div[style*="background-color: rgb(14"],
        div[style*="background-color: rgb(38"],
        div[style*="background-color: rgb(49"],
        div[style*="background: rgb(14"],
        div[style*="background: rgb(38"],
        div[style*="background: rgb(49"] {{
            background-color: white !important;
            background: white !important;
        }}

        /* Force white on any Streamlit generated containers */
        [class*="st-emotion-cache"] {{
            background-color: transparent !important;
        }}

        /* Specific targeting for block containers */
        .element-container,
        [data-testid="stVerticalBlock"],
        [data-testid="stHorizontalBlock"] {{
            background: transparent !important;
        }}

        /* ===== GLOBAL STYLES ===== */
        .stApp {{
            font-family: {TYPOGRAPHY['font_family']};
        }}

        /* ===== GLASS MORPHISM CARDS ===== */
        .glass-card {{
            background: white;
            border-radius: {RADIUS['2xl']};
            border: 1px solid {COLORS['gray_200']};
            box-shadow: {SHADOWS['md']};
            padding: {SPACING['lg']};
            margin: {SPACING['md']} 0;
        }}

        .glass-card-elevated {{
            background: white;
            border-radius: {RADIUS['xl']};
            border: 1px solid {COLORS['gray_200']};
            box-shadow: {SHADOWS['lg']};
            padding: {SPACING['xl']};
            margin: {SPACING['lg']} 0;
        }}

        /* ===== TYPOGRAPHY ===== */
        h1, h2, h3, h4, h5, h6 {{
            color: {COLORS['text_primary']} !important;
            font-weight: {TYPOGRAPHY['weight_semibold']} !important;
        }}

        h1 {{
            font-size: {TYPOGRAPHY['text_3xl']} !important;
        }}

        h2 {{
            font-size: {TYPOGRAPHY['text_2xl']} !important;
        }}

        h3 {{
            font-size: {TYPOGRAPHY['text_xl']} !important;
        }}

        p, div, span {{
            color: {COLORS['text_primary']};
        }}

        code {{
            font-family: {TYPOGRAPHY['font_family_mono']};
            font-size: {TYPOGRAPHY['text_sm']};
        }}

        /* ===== BUTTONS ===== */
        .stButton button {{
            background: {COLORS['primary']} !important;
            color: {COLORS['text_inverse']} !important;
            border: none !important;
            border-radius: {RADIUS['lg']} !important;
            padding: {SPACING['sm']} {SPACING['lg']} !important;
            font-weight: {TYPOGRAPHY['weight_medium']} !important;
            backdrop-filter: blur(10px);
            box-shadow: {SHADOWS['primary']} !important;
            transition: all 0.2s ease !important;
            cursor: pointer !important;
        }}

        .stButton button:hover {{
            background: {COLORS['primary_hover']} !important;
            box-shadow: 0 6px 20px rgba(0, 122, 255, 0.4) !important;
            transform: translateY(-2px);
        }}

        .stButton button:active {{
            transform: translateY(0);
        }}

        .stButton button:disabled {{
            opacity: 0.5;
            cursor: not-allowed !important;
            transform: none !important;
        }}

        /* Secondary Button Variant */
        .stButton.secondary button {{
            background: rgba(0, 0, 0, 0.05) !important;
            color: {COLORS['text_primary']} !important;
            box-shadow: none !important;
        }}

        .stButton.secondary button:hover {{
            background: rgba(0, 0, 0, 0.1) !important;
        }}

        /* Danger Button Variant */
        .stButton.danger button {{
            background: {COLORS['danger']} !important;
            box-shadow: 0 4px 15px rgba(220, 53, 69, 0.3) !important;
        }}

        .stButton.danger button:hover {{
            background: #c82333 !important;
        }}

        /* ===== INPUT FIELDS ===== */

        /* Fix ALL text inputs and textareas */
        textarea,
        input[type="text"],
        input[type="email"],
        input[type="password"],
        .stTextInput input,
        .stTextArea textarea,
        .stSelectbox select,
        [data-baseweb="input"],
        [data-baseweb="textarea"] {{
            background-color: white !important;
            background: white !important;
            color: {COLORS['text_primary']} !important;
            border: 1px solid {COLORS['gray_300']} !important;
            border-radius: {RADIUS['lg']} !important;
            padding: {SPACING['md']} !important;
            font-weight: {TYPOGRAPHY['weight_normal']} !important;
            transition: all 0.2s ease !important;
        }}

        /* Focus states */
        textarea:focus,
        input:focus,
        .stTextInput input:focus,
        .stTextArea textarea:focus,
        .stSelectbox select:focus {{
            border-color: {COLORS['primary']} !important;
            box-shadow: 0 0 0 3px {COLORS['primary_light']} !important;
            outline: none !important;
            background-color: white !important;
        }}

        /* Placeholders */
        textarea::placeholder,
        input::placeholder,
        .stTextInput input::placeholder,
        .stTextArea textarea::placeholder {{
            color: {COLORS['text_secondary']} !important;
            opacity: 1 !important;
        }}

        /* Input Labels */
        .stTextInput label,
        .stTextArea label,
        .stSelectbox label,
        label {{
            color: {COLORS['text_primary']} !important;
            font-weight: {TYPOGRAPHY['weight_medium']} !important;
            font-size: {TYPOGRAPHY['text_sm']} !important;
            margin-bottom: {SPACING['xs']} !important;
        }}

        /* Chat input specific fixes */
        [data-testid="stChatInput"],
        [data-testid="stChatInputTextArea"],
        [data-testid="stChatInput"] textarea,
        [data-baseweb="input"] > div {{
            background-color: white !important;
            color: {COLORS['text_primary']} !important;
            border-color: {COLORS['gray_300']} !important;
        }}

        /* ===== CHAT MESSAGES ===== */
        .user-message {{
            background: {COLORS['primary']};
            color: white;
            padding: {SPACING['md']} {SPACING['lg']};
            border-radius: {RADIUS['2xl']};
            margin: {SPACING['sm']} 0;
            max-width: 70%;
            float: right;
            clear: both;
            box-shadow: {SHADOWS['md']};
            animation: slideInRight 0.3s ease-out;
        }}

        .assistant-message {{
            background: {COLORS['gray_100']};
            color: {COLORS['text_primary']};
            padding: {SPACING['md']} {SPACING['lg']};
            border-radius: {RADIUS['2xl']};
            margin: {SPACING['sm']} 0;
            max-width: 70%;
            float: left;
            clear: both;
            box-shadow: {SHADOWS['sm']};
            animation: slideInLeft 0.3s ease-out;
        }}

        @keyframes slideInRight {{
            from {{
                opacity: 0;
                transform: translateX(20px);
            }}
            to {{
                opacity: 1;
                transform: translateX(0);
            }}
        }}

        @keyframes slideInLeft {{
            from {{
                opacity: 0;
                transform: translateX(-20px);
            }}
            to {{
                opacity: 1;
                transform: translateX(0);
            }}
        }}

        /* ===== STATUS BADGES ===== */
        .status-badge {{
            display: inline-block;
            padding: {SPACING['xs']} {SPACING['md']};
            border-radius: {RADIUS['full']};
            font-size: {TYPOGRAPHY['text_sm']};
            font-weight: {TYPOGRAPHY['weight_medium']};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .status-pending {{
            background: {COLORS['warning_light']};
            color: #856404;
            border: 1px solid {COLORS['warning']};
        }}

        .status-approved {{
            background: {COLORS['success_light']};
            color: #155724;
            border: 1px solid {COLORS['success']};
        }}

        .status-rejected {{
            background: {COLORS['danger_light']};
            color: #721c24;
            border: 1px solid {COLORS['danger']};
        }}

        .status-in-progress {{
            background: {COLORS['info_light']};
            color: #0c5460;
            border: 1px solid {COLORS['info']};
        }}

        .status-critical {{
            background: {COLORS['danger']};
            color: white;
            border: 2px solid #a71d2a;
            font-weight: {TYPOGRAPHY['weight_bold']};
            box-shadow: 0 0 10px rgba(220, 53, 69, 0.5);
            animation: pulse 2s infinite;
        }}

        @keyframes pulse {{
            0%, 100% {{
                opacity: 1;
            }}
            50% {{
                opacity: 0.8;
            }}
        }}

        /* ===== TABLES / DATAFRAMES ===== */
        .stDataFrame {{
            background: white !important;
            border-radius: {RADIUS['lg']};
            overflow: hidden;
            border: 1px solid {COLORS['gray_200']};
        }}

        .stDataFrame table {{
            background: white !important;
            color: {COLORS['text_primary']} !important;
        }}

        .stDataFrame thead {{
            background: {COLORS['gray_50']} !important;
        }}

        .stDataFrame th {{
            background: {COLORS['gray_50']} !important;
            color: {COLORS['text_primary']} !important;
            font-weight: {TYPOGRAPHY['weight_semibold']} !important;
            padding: {SPACING['md']} !important;
            border-bottom: 2px solid {COLORS['gray_200']} !important;
        }}

        .stDataFrame td {{
            background: white !important;
            color: {COLORS['text_primary']} !important;
            padding: {SPACING['md']} !important;
            border-bottom: 1px solid {COLORS['gray_100']} !important;
        }}

        .stDataFrame tr:hover td {{
            background: {COLORS['gray_50']} !important;
        }}

        /* Fix Streamlit's default dark table styling */
        [data-testid="stDataFrame"] {{
            background: white !important;
        }}

        [data-testid="stDataFrame"] div[data-testid="stDataFrameResizable"] {{
            background: white !important;
        }}

        /* ===== SIDEBAR ===== */
        section[data-testid="stSidebar"] {{
            background: {COLORS['gray_50']} !important;
            border-right: 1px solid {COLORS['gray_200']};
        }}

        section[data-testid="stSidebar"] > div {{
            background: {COLORS['gray_50']} !important;
        }}

        /* ===== PROGRESS BAR ===== */
        .stProgress > div > div {{
            background: linear-gradient(90deg, rgba(0, 122, 255, 0.8), rgba(0, 184, 255, 0.8));
            border-radius: {RADIUS['full']};
        }}

        /* ===== ALERTS ===== */
        .stAlert {{
            background: rgba(255, 255, 255, 0.85) !important;
            backdrop-filter: blur(10px);
            border-radius: {RADIUS['lg']} !important;
            border: 1px solid rgba(0, 0, 0, 0.1) !important;
        }}

        .stAlert p, .stAlert div {{
            color: {COLORS['text_primary']} !important;
        }}

        /* ===== EXPANDABLE SECTIONS ===== */
        .streamlit-expanderHeader {{
            background: rgba(255, 255, 255, 0.7);
            backdrop-filter: blur(10px);
            border-radius: {RADIUS['lg']};
            padding: {SPACING['md']};
        }}

        /* ===== METRICS / KPI CARDS ===== */
        [data-testid="stMetric"] {{
            background: white !important;
            padding: {SPACING['md']};
            border-radius: {RADIUS['lg']};
            border: 1px solid {COLORS['gray_200']};
        }}

        [data-testid="stMetricLabel"] {{
            color: {COLORS['text_secondary']} !important;
            font-size: {TYPOGRAPHY['text_sm']} !important;
        }}

        [data-testid="stMetricValue"] {{
            color: {COLORS['text_primary']} !important;
            font-weight: {TYPOGRAPHY['weight_semibold']} !important;
            font-size: {TYPOGRAPHY['text_2xl']} !important;
        }}

        [data-testid="stMetricDelta"] {{
            font-size: {TYPOGRAPHY['text_sm']} !important;
        }}

        /* ===== TABS ===== */
        .stTabs [data-baseweb="tab-list"] {{
            gap: {SPACING['sm']};
            background: rgba(255, 255, 255, 0.5);
            backdrop-filter: blur(10px);
            border-radius: {RADIUS['lg']};
            padding: {SPACING['sm']};
        }}

        .stTabs [data-baseweb="tab"] {{
            background: transparent;
            border-radius: {RADIUS['md']};
            color: {COLORS['text_primary']};
            font-weight: {TYPOGRAPHY['weight_medium']};
            padding: {SPACING['sm']} {SPACING['md']};
            transition: all 0.2s ease;
        }}

        .stTabs [aria-selected="true"] {{
            background: {COLORS['primary_light']};
            backdrop-filter: blur(10px);
            color: {COLORS['primary']};
        }}

        /* ===== CODE BLOCKS ===== */
        .stCodeBlock {{
            background: rgba(255, 255, 255, 0.7) !important;
            backdrop-filter: blur(10px);
            border-radius: {RADIUS['lg']} !important;
            border: 1px solid rgba(0, 0, 0, 0.1);
        }}

        /* ===== FORM CONTAINERS ===== */
        .stForm {{
            background: rgba(255, 255, 255, 0.6);
            backdrop-filter: blur(15px);
            border-radius: {RADIUS['xl']};
            padding: {SPACING['xl']};
            border: 1px solid rgba(255, 255, 255, 0.5);
        }}

        /* ===== FIX MODALS & DIALOGS ===== */
        [data-testid="stModal"],
        [data-baseweb="modal"],
        .stModal,
        [role="dialog"] {{
            background-color: white !important;
        }}

        /* Fix any dark overlays or backdrops */
        [data-baseweb="modal"] > div {{
            background-color: rgba(0, 0, 0, 0.5) !important;
        }}

        /* Fix selectbox dropdowns */
        [data-baseweb="popover"],
        [data-baseweb="menu"],
        [role="listbox"] {{
            background-color: white !important;
            color: {COLORS['text_primary']} !important;
        }}

        /* Fix checkboxes and radio buttons */
        .stCheckbox,
        .stRadio,
        [data-baseweb="checkbox"],
        [data-baseweb="radio"] {{
            background-color: transparent !important;
        }}

        /* ===== FIX STREAMLIT SPINNER/LOADER ===== */
        .stSpinner > div,
        [data-testid="stSpinner"] {{
            background-color: transparent !important;
        }}

        /* ===== ANIMATIONS ===== */
        @media (prefers-reduced-motion: reduce) {{
            * {{
                animation: none !important;
                transition: none !important;
            }}
        }}

        /* ===== FINAL CATCH-ALL FOR DARK ELEMENTS ===== */
        /* Remove any remaining dark backgrounds */
        div[style*="background-color: rgb(14"],
        div[style*="background-color: rgb(38"],
        div[style*="background: rgb(14"],
        div[style*="background: rgb(38"] {{
            background-color: white !important;
            background: white !important;
        }}

        /* ===== LOADING STATES ===== */
        .stSpinner > div {{
            border-top-color: {COLORS['primary']} !important;
        }}

        /* ===== TOOLTIPS ===== */
        [data-baseweb="tooltip"] {{
            background: rgba(0, 0, 0, 0.9) !important;
            backdrop-filter: blur(10px);
            border-radius: {RADIUS['md']};
            font-size: {TYPOGRAPHY['text_sm']};
        }}
    </style>
    """


# ============================================================================
# COMPONENT FUNCTIONS
# ============================================================================

def render_status_badge(status: str) -> str:
    """
    Render a status badge with appropriate styling

    Args:
        status: Status string (pending, approved, rejected, in_progress, critical)

    Returns:
        HTML string for the badge
    """
    status_lower = status.lower().replace('_', '-')
    status_display = status.replace('_', ' ').title()

    return f'<span class="status-badge status-{status_lower}">{status_display}</span>'


def render_metric_card(label: str, value: str, delta: str = None, help_text: str = None) -> str:
    """
    Render a KPI metric card

    Args:
        label: Metric label
        value: Metric value
        delta: Optional delta/change value
        help_text: Optional tooltip text

    Returns:
        HTML string for metric card
    """
    delta_html = f'<div class="metric-delta">{delta}</div>' if delta else ''
    help_html = f'<span class="metric-help" title="{help_text}">ⓘ</span>' if help_text else ''

    return f"""
    <div class="glass-card" style="text-align: center;">
        <div style="font-size: {TYPOGRAPHY['text_sm']}; color: {COLORS['text_secondary']}; margin-bottom: {SPACING['xs']};">
            {label} {help_html}
        </div>
        <div style="font-size: {TYPOGRAPHY['text_2xl']}; font-weight: {TYPOGRAPHY['weight_semibold']}; color: {COLORS['text_primary']};">
            {value}
        </div>
        {delta_html}
    </div>
    """


def get_app_navigation_header(role: str = 'researcher') -> str:
    """
    Render navigation header with links based on user role

    NOTE: This returns CSS for the navigation bar styling.
    The actual navigation links are rendered in the apps using the
    render_app_navigation_links() function which uses Streamlit components.

    Args:
        role: User role - 'researcher' or 'admin'
            - researcher: Shows Researcher Portal + Research Notebook only
            - admin: Shows all three apps

    Returns:
        CSS string for navigation header styling
    """
    # Return CSS for navigation bar (HTML rendering didn't work in Streamlit 1.29.0)
    return f"""
    <style>
        .nav-header {{
            background: white;
            border: 1px solid {COLORS['gray_200']};
            border-radius: {RADIUS['xl']};
            padding: {SPACING['md']} {SPACING['lg']};
            margin-bottom: {SPACING['lg']};
            box-shadow: {SHADOWS['sm']};
        }}

        .nav-link {{
            display: inline-block;
            padding: {SPACING['sm']} {SPACING['md']};
            border-radius: {RADIUS['md']};
            text-decoration: none;
            color: {COLORS['text_primary']};
            background: transparent;
            transition: background 0.2s ease;
            margin-right: {SPACING['sm']};
            border: 1px solid transparent;
        }}

        .nav-link:hover {{
            background: {COLORS['primary_light']};
            border-color: {COLORS['primary']};
        }}

        .nav-link.active {{
            background: {COLORS['primary']};
            color: white;
        }}
    </style>
    """


def render_app_navigation_links(role: str = 'researcher') -> str:
    """
    Render clickable navigation links using simple HTML without JavaScript

    This function works better with Streamlit's HTML sanitization than
    the previous approach with inline event handlers.

    Args:
        role: User role - 'researcher' or 'admin'

    Returns:
        HTML string with navigation links (no JavaScript)
    """
    portal_link = f'<a href="http://localhost:8501" target="_blank" class="nav-link">🔬 Researcher Portal</a>'
    admin_link = f'<a href="http://localhost:8502" target="_blank" class="nav-link">⚙️ Admin Dashboard</a>'
    notebook_link = f'<a href="http://localhost:8503" target="_blank" class="nav-link">🤖 Research Notebook</a>'

    links = portal_link
    if role == 'admin':
        links += admin_link
    links += notebook_link

    return f"""
    <div class="nav-header">
        <strong style="margin-right: 2rem; color: {COLORS['text_primary']};">ResearchFlow</strong>
        {links}
    </div>
    """


def render_critical_alert(title: str, message: str) -> str:
    """
    Render a critical alert box (for SQL reviews, etc.)

    Args:
        title: Alert title
        message: Alert message

    Returns:
        HTML string for critical alert
    """
    return f"""
    <div style="
        background: {COLORS['danger_light']};
        border: 2px solid {COLORS['danger']};
        border-radius: {RADIUS['lg']};
        padding: {SPACING['lg']};
        margin: {SPACING['md']} 0;
        box-shadow: 0 0 20px rgba(220, 53, 69, 0.3);
    ">
        <div style="
            display: flex;
            align-items: center;
            gap: {SPACING['md']};
            margin-bottom: {SPACING['sm']};
        ">
            <span style="font-size: {TYPOGRAPHY['text_2xl']};">⚠️</span>
            {render_status_badge('critical')}
            <span style="
                font-size: {TYPOGRAPHY['text_lg']};
                font-weight: {TYPOGRAPHY['weight_semibold']};
                color: {COLORS['danger']};
            ">{title}</span>
        </div>
        <div style="color: #721c24; font-size: {TYPOGRAPHY['text_base']};">
            {message}
        </div>
    </div>
    """
