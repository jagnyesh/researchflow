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
    """Manages conversational flow for research notebook

    Uses hybrid intent detection:
    - Pattern matching for clear/simple intents (fast path - 90% of cases)
    - LLM fallback for ambiguous cases (slow path - 10% of cases)
    """

    def __init__(self):
        # Import LLM client for fallback
        from app.utils.llm_client import LLMClient

        self.llm_client = LLMClient()

        # Performance tracking
        self._total_calls = 0
        self._pattern_matches = 0
        self._llm_fallbacks = 0

        # Greeting keywords
        self.greeting_keywords = [
            "hi",
            "hello",
            "hey",
            "greetings",
            "good morning",
            "good afternoon",
            "good evening",
            "howdy",
        ]

        # Confirmation keywords
        self.confirmation_keywords = [
            "yes",
            "yeah",
            "yep",
            "sure",
            "ok",
            "okay",
            "proceed",
            "continue",
            "go ahead",
            "confirm",
        ]

        # Rejection keywords
        self.rejection_keywords = ["no", "nope", "cancel", "stop", "don't", "refine"]

        # Status check keywords
        self.status_keywords = [
            "status",
            "where",
            "what's happening",
            "progress",
            "how long",
            "when",
            "ready",
        ]

        # Help keywords (IMPROVED - removed ambiguous "how")
        self.help_keywords = [
            "help me",
            "what can you do",
            "show me features",
            "capabilities",
            "guide",
            "instructions",
            "how do i",  # More specific than "how"
            "how can i",  # More specific than "how"
            "how does",  # More specific than "how"
        ]

        # Query pattern keywords (NEW - for detecting data queries)
        self.query_keywords = [
            "how many",
            "show me",
            "give me",
            "count",
            "find",
            "list",
            "patients with",
            "breakdown",
            "broken down",
            "filter",
            "get all",
        ]

        # Negative keywords (indicate NOT that intent)
        self.negative_keywords = ["don't", "not", "never", "no"]

    async def detect_intent(self, user_input: str) -> UserIntent:
        """
        Hybrid intent detection: Pattern matching with LLM fallback

        Strategy:
        1. Try pattern matching (fast path - 90% of cases)
        2. If ambiguous or no match, use LLM (slow path - 10% of cases)

        Args:
            user_input: User's message

        Returns:
            UserIntent enum value
        """
        self._total_calls += 1
        user_input_lower = user_input.lower().strip()

        # Step 1: Check for negation (skip patterns if negative context)
        # But exclude simple "no" responses (those are rejections, not negative context)
        has_negation = (
            any(neg in user_input_lower for neg in self.negative_keywords)
            and user_input_lower not in self.rejection_keywords
        )

        if has_negation:
            # Negative context detected - use LLM for accurate classification
            logger.debug(f"Negation detected in: '{user_input}' - using LLM")
            self._llm_fallbacks += 1
            return await self._llm_fallback(user_input)

        # Step 2: Pattern matching - collect all matches
        matches = []

        # Check greeting
        if any(keyword in user_input_lower for keyword in self.greeting_keywords):
            if len(user_input_lower.split()) <= 3:
                matches.append(UserIntent.GREETING)

        # Check query patterns FIRST (prioritize over help)
        if any(pattern in user_input_lower for pattern in self.query_keywords):
            matches.append(UserIntent.QUERY)

        # Check help (now checks after query patterns)
        if any(keyword in user_input_lower for keyword in self.help_keywords):
            matches.append(UserIntent.HELP)

        # Check status
        if any(keyword in user_input_lower for keyword in self.status_keywords):
            matches.append(UserIntent.STATUS_CHECK)

        # Check confirmation (exact match only)
        if user_input_lower in self.confirmation_keywords:
            matches.append(UserIntent.CONFIRMATION)

        # Step 3: Resolve matches
        if len(matches) == 0:
            # No pattern match - use LLM
            logger.debug(f"No pattern match for: '{user_input}' - using LLM")
            self._llm_fallbacks += 1
            return await self._llm_fallback(user_input)

        elif len(matches) == 1:
            # Unambiguous - return immediately (FAST PATH)
            logger.debug(f"Pattern match: '{user_input}' -> {matches[0].value}")
            self._pattern_matches += 1
            return matches[0]

        else:
            # Ambiguous (multiple matches) - use LLM
            logger.debug(f"Ambiguous intent for: '{user_input}' (matches: {matches}) - using LLM")
            self._llm_fallbacks += 1
            return await self._llm_fallback(user_input)

    async def _llm_fallback(self, user_input: str) -> UserIntent:
        """
        Use LLM to classify intent when patterns are ambiguous or fail

        Args:
            user_input: User's message

        Returns:
            UserIntent from LLM classification
        """
        try:
            prompt = f"""Classify this user message into ONE intent category.

Intent Categories:
- GREETING: User is greeting you (e.g., "hi", "hello")
- HELP: User needs assistance (e.g., "what can you do?", "help me")
- QUERY: User wants data/information (e.g., "show me patients", "how many diabetic patients?")
- STATUS_CHECK: User checking request status (e.g., "what's the status?", "is it ready?")
- CONFIRMATION: User confirming action (e.g., "yes", "proceed", "go ahead")
- UNKNOWN: Cannot determine

User message: "{user_input}"

Respond with ONLY the intent category name.
Intent:"""

            response = await self.llm_client.complete(
                prompt=prompt,
                max_tokens=20,
                temperature=0.0,  # Deterministic
            )

            intent_str = response.strip().upper()

            # Map to UserIntent enum
            if "GREETING" in intent_str:
                return UserIntent.GREETING
            elif "HELP" in intent_str:
                return UserIntent.HELP
            elif "QUERY" in intent_str:
                return UserIntent.QUERY
            elif "STATUS" in intent_str:
                return UserIntent.STATUS_CHECK
            elif "CONFIRM" in intent_str:
                return UserIntent.CONFIRMATION
            else:
                return UserIntent.UNKNOWN

        except Exception as e:
            logger.error(f"LLM intent detection failed: {e}")
            # Defensive fallback: default to QUERY (most common)
            return UserIntent.QUERY

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
        self, cohort_size: int, feasibility_data: Dict[str, Any]
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
            response += (
                f"**Time Period:** {time_period.get('start')} to {time_period.get('end')}\n\n"
            )

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
        self, request_id: str, current_state: str, approval_status: Optional[Dict[str, Any]] = None
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

    def format_confirmation_request(self, action: str, details: Dict[str, Any]) -> str:
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

    async def is_confirmation(self, user_input: str) -> bool:
        """Check if user input is a confirmation"""
        # First check if it's a rejection (rejections are definitely not confirmations)
        if await self.is_rejection(user_input):
            return False

        intent = await self.detect_intent(user_input)
        return intent == UserIntent.CONFIRMATION

    async def is_rejection(self, user_input: str) -> bool:
        """
        Check if user input is a rejection

        Uses pattern matching first, LLM fallback for complex rejections
        """
        user_input_lower = user_input.lower().strip()

        # Quick pattern check first
        if user_input_lower in self.rejection_keywords:
            return True

        # LLM fallback for complex rejections
        try:
            prompt = f"""Is this message a rejection or refusal? Answer YES or NO.

Examples of rejections: "no", "cancel", "don't proceed", "stop", "I don't want to"
Examples of non-rejections: "yes", "okay", "show me more"

Message: "{user_input}"

Answer (YES or NO):"""

            response = await self.llm_client.complete(prompt=prompt, max_tokens=5, temperature=0.0)
            return "YES" in response.upper()

        except Exception as e:
            logger.error(f"LLM rejection detection failed: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics for intent detection

        Returns:
            Dictionary with stats: total_calls, pattern_matches, llm_fallbacks, llm_percentage
        """
        total = max(self._total_calls, 1)  # Avoid division by zero
        return {
            "total_calls": self._total_calls,
            "pattern_matches": self._pattern_matches,
            "llm_fallbacks": self._llm_fallbacks,
            "llm_percentage": (self._llm_fallbacks / total) * 100,
            "pattern_percentage": (self._pattern_matches / total) * 100,
        }
