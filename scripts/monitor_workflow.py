#!/usr/bin/env python3
"""
Real-time workflow monitor for ResearchFlow testing.
Watches the latest request and displays state transitions in real-time.
"""

import asyncio
import sys
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker


class WorkflowMonitor:
    def __init__(self, db_url="sqlite+aiosqlite:///./dev.db"):
        self.engine = create_async_engine(db_url)
        self.async_session = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.last_state = None
        self.last_agent_count = 0

    async def get_latest_request(self):
        """Get the latest research request"""
        async with self.async_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT request_id, workflow_state, current_agent, current_task,
                           researcher_name, study_title, created_at, updated_at
                    FROM research_request
                    ORDER BY created_at DESC
                    LIMIT 1
                """
                )
            )
            return result.fetchone()

    async def get_agent_executions(self, request_id):
        """Get agent executions for a request"""
        async with self.async_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT agent_id, task, status, error_message, started_at, completed_at
                    FROM agent_execution
                    WHERE request_id = :rid
                    ORDER BY started_at DESC
                """
                ),
                {"rid": request_id},
            )
            return result.fetchall()

    async def get_pending_approvals(self, request_id):
        """Get pending approvals for a request"""
        async with self.async_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT approval_type, status, created_at
                    FROM approval
                    WHERE request_id = :rid AND status = 'pending'
                    ORDER BY created_at DESC
                """
                ),
                {"rid": request_id},
            )
            return result.fetchall()

    def print_header(self):
        """Print monitoring header"""
        print("\n" + "=" * 80)
        print("ResearchFlow Workflow Monitor")
        print("=" * 80)
        print("Press Ctrl+C to stop monitoring\n")

    def print_request_info(self, request):
        """Print request information"""
        print(f"📋 Request: {request[0]}")
        print(f"   Researcher: {request[4]}")
        print(f"   Study: {request[5]}")
        print(f"   Created: {request[6]}")
        print(f"   Updated: {request[7]}")
        print(f"\n🔄 Current State: {request[1]}")
        print(f"   Agent: {request[2] or 'None'}")
        print(f"   Task: {request[3] or 'None'}")

    def print_agent_executions(self, executions):
        """Print agent execution summary"""
        if not executions:
            print("\n📊 Agent Executions: None")
            return

        print(f"\n📊 Agent Executions: {len(executions)} total")
        print("\n   Recent executions:")
        for idx, exe in enumerate(executions[:5], 1):
            status_icon = "✅" if exe[2] == "completed" else "❌" if exe[2] == "failed" else "⏳"
            print(f"   {status_icon} [{idx}] {exe[0]} - {exe[1]}: {exe[2]}")
            if exe[3]:  # error_message
                print(f"       ⚠️  Error: {exe[3]}")
            duration = "In progress"
            if exe[5]:  # completed_at
                start = datetime.fromisoformat(exe[4])
                end = datetime.fromisoformat(exe[5])
                duration = f"{(end - start).total_seconds():.1f}s"
            print(f"       ⏱️  Duration: {duration}")

    def print_approvals(self, approvals):
        """Print pending approvals"""
        if not approvals:
            print("\n✋ Pending Approvals: None")
            return

        print(f"\n✋ Pending Approvals: {len(approvals)}")
        for approval in approvals:
            print(f"   🔔 {approval[0]}: {approval[1]} (created {approval[2]})")
            print(f"      👉 Action required in Admin Dashboard!")

    def print_update_indicator(self, changed):
        """Print update indicator"""
        if changed:
            print(f"\n🔄 State changed at {datetime.now().strftime('%H:%M:%S')}")

    async def monitor(self, interval=5):
        """Monitor workflow in real-time"""
        self.print_header()

        try:
            while True:
                request = await self.get_latest_request()

                if not request:
                    print("⚠️  No requests found in database")
                    await asyncio.sleep(interval)
                    continue

                request_id = request[0]
                current_state = request[1]

                # Check if state changed
                state_changed = self.last_state != current_state

                # Clear screen and reprint
                if state_changed:
                    print("\n" + "=" * 80)
                    self.print_update_indicator(True)

                self.print_request_info(request)

                # Get agent executions
                executions = await self.get_agent_executions(request_id)
                self.print_agent_executions(executions)

                # Get pending approvals
                approvals = await self.get_pending_approvals(request_id)
                self.print_approvals(approvals)

                # Update tracking variables
                self.last_state = current_state
                self.last_agent_count = len(executions)

                print(f"\n⏳ Next update in {interval} seconds...")
                print("=" * 80)

                await asyncio.sleep(interval)

        except KeyboardInterrupt:
            print("\n\n👋 Monitoring stopped by user")
        except Exception as e:
            print(f"\n\n❌ Error: {e}")
            import traceback

            traceback.print_exc()

    async def run_once(self):
        """Run monitoring once (single snapshot)"""
        self.print_header()

        request = await self.get_latest_request()

        if not request:
            print("⚠️  No requests found in database")
            return

        request_id = request[0]

        self.print_request_info(request)

        executions = await self.get_agent_executions(request_id)
        self.print_agent_executions(executions)

        approvals = await self.get_pending_approvals(request_id)
        self.print_approvals(approvals)

        print("\n" + "=" * 80)


async def main():
    """Main entry point"""
    monitor = WorkflowMonitor()

    # Check if --once flag is provided
    if "--once" in sys.argv:
        await monitor.run_once()
    else:
        # Continuous monitoring
        interval = 5
        if "--interval" in sys.argv:
            idx = sys.argv.index("--interval")
            if idx + 1 < len(sys.argv):
                interval = int(sys.argv[idx + 1])

        await monitor.monitor(interval=interval)


if __name__ == "__main__":
    asyncio.run(main())
