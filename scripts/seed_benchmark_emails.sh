#!/bin/bash
# Seed emails for PetToWild benchmark tasks
# Run this before executing benchmark tasks to populate required emails

set -e

echo "🌱 Seeding benchmark emails..."

# Task 101: Email from Sarah about Q4 budget
echo "📧 Sending Q4 budget email from Sarah..."
docker compose exec -T stalwart swaks \
  --to alice@snappymail.zoo \
  --from sarah@snappymail.zoo \
  --server stalwart:25 \
  --header "Subject: Q4 Budget Meeting" \
  --body "Hi Alice, I wanted to follow up on the Q4 budget planning. Can we schedule a meeting to discuss the allocations? - Sarah"

# Task 103: Email from Bob with meeting time proposal
echo "📧 Sending meeting proposal from Bob..."
docker compose exec -T stalwart swaks \
  --to alice@snappymail.zoo \
  --from bob@snappymail.zoo \
  --server stalwart:25 \
  --header "Subject: Meeting Time Proposal" \
  --body "Hi Alice, How about we meet next Tuesday at 2:30 PM to go over the project updates? Let me know if that works. - Bob"

# Task 104: Some normal emails for triage
echo "📧 Sending normal emails for Task 104..."
docker compose exec -T stalwart swaks \
  --to alice@snappymail.zoo \
  --from hr@snappymail.zoo \
  --server stalwart:25 \
  --header "Subject: Team Lunch Next Week" \
  --body "Hi everyone, We're planning a team lunch next Thursday. Please RSVP by Monday. - HR"

docker compose exec -T stalwart swaks \
  --to alice@snappymail.zoo \
  --from sarah@snappymail.zoo \
  --server stalwart:25 \
  --header "Subject: Budget Report Ready" \
  --body "Alice, The Q4 budget report is ready for your review. It's in the shared drive. - Sarah"

echo "✅ Benchmark emails seeded successfully!"
echo ""
echo "Emails sent to alice@snappymail.zoo inbox:"
echo "  1. Sarah - Q4 Budget Meeting (for Task 101)"
echo "  2. Bob - Meeting Time Proposal (for Task 103)"
echo "  3. HR - Team Lunch (for Task 104)"
echo "  4. Sarah - Budget Report (for Task 104)"
