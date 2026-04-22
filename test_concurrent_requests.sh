#!/bin/bash
# Test concurrent request submission to reproduce threading errors

echo "Submitting 5 concurrent requests to test for threading issues..."
echo "Logs will show checkpointer instance creation patterns"
echo ""

# Submit 5 requests in parallel using background jobs
for i in {1..5}; do
  curl -X POST http://localhost:8000/api/researchflow/request \
    -H "Content-Type: application/json" \
    -d '{
      "researcher_name": "Concurrent Test '$i'",
      "researcher_email": "test'$i'@hospital.edu",
      "researcher_department": "Testing",
      "irb_number": "IRB-CONCURRENT-'$i'",
      "researcher_request": "I need demographics for male patients with diabetes (test '$i').",
      "inclusion_criteria": "male\ndiabetes",
      "data_elements": ["Demographics"]
    }' \
    > /tmp/concurrent_test_$i.json 2>&1 &

  echo "Started request $i (PID: $!)"
done

echo ""
echo "Waiting for all requests to complete..."
wait

echo ""
echo "All requests completed. Results:"
for i in {1..5}; do
  echo "Request $i:"
  cat /tmp/concurrent_test_$i.json
  echo ""
done

echo ""
echo "Check logs with: tail -f /tmp/researcher_portal.log | grep 'DEBUG Phase 2'"
