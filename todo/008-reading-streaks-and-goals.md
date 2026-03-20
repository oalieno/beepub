# 008 — Reading Streaks & Goals

## Goal

Add daily/weekly reading goals with streak tracking to gamify and encourage reading habits. Pure algorithmic — no AI, uses existing `ReadingActivity` data.

## User Story

- As a reader, I want to set a daily reading goal (e.g., 30 minutes) and see my streak so I stay motivated.
- As a reader, I want to see my weekly reading stats at a glance.

## Technical Approach

### Backend

**New endpoint**: `GET /api/reading/stats`

Returns:
```json
{
    "current_streak": 5,          // consecutive days meeting goal
    "longest_streak": 14,
    "today_seconds": 1200,        // 20 minutes so far today
    "daily_goal_seconds": 1800,   // user's goal: 30 minutes
    "goal_met_today": false,
    "this_week_seconds": 7200,    // total this week
    "this_week_days_met": 3,      // days goal was met this week
    "this_month_seconds": 28800
}
```

**Streak calculation**: Query `reading_activity` table for consecutive days where `seconds >= daily_goal_seconds`, counting backwards from today. A day with 0 seconds breaks the streak.

**Goal setting endpoint**: `PUT /api/reading/goal`
```json
{ "daily_goal_minutes": 30 }
```

Store in `UserBookInteraction` or a new `user_preferences` column/table. Simplest: add a `daily_reading_goal_seconds` column to `users` table (nullable, default null = no goal set).

### Frontend

**Home page widget**: A compact card showing:
- Current streak with flame icon (`Flame` from lucide-svelte)
- Today's progress bar (e.g., "20/30 min")
- "Goal met!" celebration state when reached

**Reading Activity Heatmap enhancement**: The existing `ReadingActivityHeatmap.svelte` can be extended to show goal-met days with a different color/intensity.

**Goal setting**: Simple modal in settings or on first visit to streak widget. Slider or input for daily minutes (15, 30, 45, 60, custom).

### Edge Cases

- No goal set → show reading stats without streak (streak requires a goal)
- Timezone: use the user's timezone (already handled by reading activity tracking) to determine "today"
- Day with reading but below goal → breaks streak but still shows in heatmap

## Key Files

- `backend/app/models/reading.py` — `ReadingActivity` model (existing)
- `backend/app/models/user.py` — add `daily_reading_goal_seconds` column
- `backend/app/routers/books.py` — add stats + goal endpoints (or new `backend/app/routers/reading.py`)
- `frontend/src/lib/components/ReadingStreakCard.svelte` — new component
- `frontend/src/lib/components/ReadingActivityHeatmap.svelte` — enhance with goal overlay
- `frontend/src/routes/+page.svelte` — add streak card to home page
- Alembic migration for new column

## Dependencies

None. Uses only existing data.

## Verification

- Set a daily goal → streak starts counting from today
- Read for goal amount → "Goal met!" shows
- Skip a day → streak resets to 0
- No goal set → stats show without streak info
- Check streak calculation across timezone boundaries
- Verify stats endpoint is efficient (single SQL query, not N+1)
