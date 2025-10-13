"""
Conversation Manager for Research Notebook

Handles conversational AI layer including:
- Intent detection (greeting vs query vs status check)
- Context management
- Response formatting
- Capability explanations
"""

from typing import Dict, Any, Optional, Literal
from enum import Enum
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class UserIntent(Enum):
    """Types of user intents"""
    GREETING = "greeting"
    QUERY = "query"
    STATUS_CHECK = "status_check"
    CONFIRMATION = "confirmation"
    HELP = "help"
    UNKNOWN = "unknown"


class ConversationState(Enum):
    """Conversation states"""
    INITIAL = "initial"
    GATHERING_REQUIREMENTS = "gathering_requirements"
    SHOWING_FEASIBILITY = "showing_feasibility"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AWAITING_APPROVAL = "awaiting_approval"
    EXTRACTION_RUNNING = "extraction_running"
    COMPLETED = "completed"


class ConversationManager:
    """Manages conversational flow for research notebook"""

    def __init__(self):
        self.greeting_keywords = [
            "hi", "hello", "hey", "greetings", "good morning",
            "good afternoon", "good evening", "howdy"
        ]
        self.confirmation_keywords = [
            "yes", "yeah", "yep", "sure", "ok", "okay", "proceed",
            "continue", "go ahead", "confirm"
        ]
        self.rejection_keywords = [
            "no", "nope", "cancel", "stop", "don't", "refine"
        ]
        self.status_keywords = [
            "status", "where", "what's happening", "progress",
            "how long", "when", "ready"
        ]
        self.help_keywords = [
            "help", "how", "what can you do", "capabilities",
            "features", "guide"
        ]

    def detect_intent(self, user_input: str) -> UserIntent:
        """
        Detect user intent from input text

        Args:
            user_input: User's message

        Returns:
            UserIntent enum value
        """
        user_input_lower = user_input.lower().strip()

        # Check for greeting
        if any(keyword in user_input_lower for keyword in self.greeting_keywords):
            # If it's ONLY a greeting (short message), return GREETING
            if len(user_input_lower.split()) <= 3:
                return UserIntent.GREETING

        # Check for help
        if any(keyword in user_input_lower for keyword in self.help_keywords):
            return UserIntent.HELP

        # Check for status check
        if any(keyword in user_input_lower for keyword in self.status_keywords):
            return UserIntent.STATUS_CHECK

        # Check for confirmation
        if user_input_lower in self.confirmation_keywords:
            return UserIntent.CONFIRMATION

        # Check for rejection
        if user_input_lower in self.rejection_keywords:
            return UserIntent.CONFIRMATION  # Same intent, but with different value

        # If contains medical/query terms, it's a query
        if len(user_input_lower.split()) > 3:
            return UserIntent.QUERY

        return UserIntent.UNKNOWN

    def get_introduction(self) -> str:
        """Get introduction message"""
        return """Hello! I'm **ResearchFlow**, your AI-powered research assistant for clinical data requests.

### What I Can Do:

🔍 **Explore Data**
- Answer questions about patient populations
- Show summary statistics and cohort sizes
- Calculate data availability and completeness

📊 **Submit Data Requests**
- Extract structured requirements from your research questions
- Generate SQL queries with informatician review
- Coordinate approval workflows automatically

🔐 **Ensure Compliance**
- All extractions require informatician approval
- Complete audit trail for regulatory compliance
- De-identification support for PHI protection

### How It Works:

1. **Ask a question** - I'll analyze your research criteria
2. **Review feasibility** - See cohort size and data availability
3. **Confirm extraction** - Approve submission for formal data request
4. **Track progress** - Monitor approval status in real-time
5. **Receive data** - Download when informatician approves

### Example Questions:

- "How many patients with diabetes are available?"
- "Show me patients with HbA1c > 8.5% in the last 6 months"
- "Get female patients with hypertension under age 65"

**What would you like to explore today?**"""

    def get_help_message(self) -> str:
        """Get help message"""
        return """### ResearchFlow Commands:

**Data Exploration:**
- Ask questions in natural language
- Use specific criteria (age, gender, conditions, labs)
- Include time periods when relevant

**Status Checks:**
- "What's the status of my request?"
- "When will my data be ready?"

**Refinement:**
- Answer "no" or "refine" to adjust criteria
- Modify inclusion/exclusion criteria
- Change data elements or time periods

**Examples:**
- ✅ "Patients with diabetes and HbA1c > 7.0%"
- ✅ "Show me hypertensive patients under 50"
- ✅ "Get all lab results for diabetic patients in 2023"

Need more help? Contact your informatician."""

    def format_feasibility_response(
        self,
        cohort_size: int,
        feasibility_data: Dict[str, Any]
    ) -> str:
        """
        Format feasibility check results

        Args:
            cohort_size: Estimated number of patients
            feasibility_data: Dictionary with feasibility metrics

        Returns:
            Formatted markdown response
        """
        response = f"""### 📊 Feasibility Analysis

**Estimated Cohort Size:** {cohort_size:,} patients

"""

        # Data availability
        if "data_availability" in feasibility_data:
            availability = feasibility_data["data_availability"]
            overall = availability.get("overall_availability", 0)

            response += f"**Overall Data Availability:** {overall:.1%}\n\n"
            response += "**By Data Element:**\n"

            for element, score in availability.get("by_element", {}).items():
                emoji = "✅" if score > 0.9 else "⚠️" if score > 0.7 else "❌"
                response += f"- {emoji} {element.replace('_', ' ').title()}: {score:.1%}\n"
            response += "\n"

        # Time period
        if "time_period" in feasibility_data:
            time_period = feasibility_data["time_period"]
            response += f"**Time Period:** {time_period.get('start')} to {time_period.get('end')}\n\n"

        # Warnings
        if "warnings" in feasibility_data and feasibility_data["warnings"]:
            response += "### ⚠️ Warnings:\n"
            for warning in feasibility_data["warnings"]:
                response += f"- {warning.get('message', warning)}\n"
            response += "\n"

        # Recommendations
        if "recommendations" in feasibility_data and feasibility_data["recommendations"]:
            response += "### 💡 Recommendations:\n"
            for rec in feasibility_data["recommendations"]:
                response += f"- {rec}\n"
            response += "\n"

        # Next steps
        response += """---

**Would you like to proceed with full data extraction?**

- Type **"yes"** to submit a formal data request
- Type **"no"** or **"refine"** to adjust your criteria
- Type **"help"** for more options

⚠️ **Note:** Full extraction requires informatician approval and may take 15-30 minutes."""

        return response

    def format_approval_status(
        self,
        request_id: str,
        current_state: str,
        approval_status: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Format approval workflow status

        Args:
            request_id: Research request ID
            current_state: Current workflow state
            approval_status: Dictionary with approval details

        Returns:
            Formatted markdown response
        """
        response = f"""### 📋 Request Status: {request_id}

**Current State:** {current_state.replace('_', ' ').title()}

"""

        # Approval pipeline
        response += """**Approval Pipeline:**

"""

        # Define approval stages
        stages = [
            ("requirements_review", "Requirements Review"),
            ("phenotype_review", "SQL Query Review"),
            ("extraction", "Data Extraction"),
            ("qa_review", "Quality Assurance"),
        ]

        for stage_key, stage_name in stages:
            if approval_status and stage_key in approval_status:
                stage_status = approval_status[stage_key]
                if stage_status == "approved":
                    response += f"✅ {stage_name}: Approved\n"
                elif stage_status == "pending":
                    response += f"⏸️ {stage_name}: Pending Review...\n"
                elif stage_status == "rejected":
                    response += f"❌ {stage_name}: Rejected\n"
            else:
                response += f"⬜ {stage_name}: Not started\n"

        response += "\n"

        # Estimated time
        if current_state in ["awaiting_approval", "phenotype_review"]:
            response += "**Estimated Time:** 1-24 hours (pending informatician review)\n"
        elif current_state == "extraction_running":
            response += "**Estimated Time:** 15-30 minutes\n"

        response += "\n💡 **Tip:** I'll notify you when the informatician approves your request!"

        return response

    def format_confirmation_request(
        self,
        action: str,
        details: Dict[str, Any]
    ) -> str:
        """
        Format confirmation request message

        Args:
            action: Action to confirm
            details: Action details

        Returns:
            Formatted confirmation message
        """
        if action == "submit_extraction":
            return f"""### ✅ Ready to Submit Data Request

**Request Summary:**
- Cohort Size: {details.get('cohort_size', 'Unknown')}
- Data Elements: {len(details.get('data_elements', []))}
- Time Period: {details.get('time_period', 'Not specified')}

**Next Steps:**
1. Submit formal data request
2. Informatician reviews SQL query
3. Data extraction (if approved)
4. Quality assurance
5. Delivery notification

**Are you sure you want to proceed?**

Type **"yes"** to submit or **"no"** to cancel."""

        return "Please confirm this action: yes/no"

    def is_confirmation(self, user_input: str) -> bool:
        """Check if user input is a confirmation"""
        return user_input.lower().strip() in self.confirmation_keywords

    def is_rejection(self, user_input: str) -> bool:
        """Check if user input is a rejection"""
        return user_input.lower().strip() in self.rejection_keywords
