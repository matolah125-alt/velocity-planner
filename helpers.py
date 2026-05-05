import sqlite3
import os
from datetime import datetime, timedelta
import math

# --- Human Constraints Configuration ---
BIG_TASK_THRESHOLD_HOURS = 3 # Tasks >= this duration are considered "big"
MAX_BIG_TASKS_PER_DAY = 2
SOCIAL_MEDIA_START_HOUR = 20 # 8:00 PM
SOCIAL_MEDIA_END_HOUR = 21 # 9:00 PM
WIND_DOWN_BUFFER_HOURS = 2 # Stop scheduling this many hours before midnight (e.g., 2 hours before 24:00 means 22:00 hard stop)

def get_db_connection():
    # Create an absolute path to the database file relative to this script's directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'database.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_optimized_plan(user_id, available_hours):
    """
    Fetch pending tasks and return an optimized list that fits within available_hours
    using the Priority/Duration greedy approach.
    """
    conn = get_db_connection()
    # Fetch all pending tasks, including manual schedule info
    all_pending_tasks = conn.execute('SELECT * FROM tasks WHERE user_id = ? AND is_completed = 0', (user_id,)).fetchall()

    # Convert to list of dicts and calculate priority score
    task_list = []
    for task in all_pending_tasks:
        t = dict(task)
        # Priority score: Higher is better (High priority + Low duration)
        t['score'] = t['priority'] / t['duration'] if t['duration'] > 0 else 0
        task_list.append(t) # This list now contains all pending tasks

    # Separate manually scheduled tasks from algorithm-scheduled tasks
    manually_scheduled_tasks = [t for t in task_list if t['is_manual_schedule'] and t['scheduled_date'] and t['scheduled_time']]
    algorithm_tasks = [t for t in task_list if not t['is_manual_schedule'] or not (t['scheduled_date'] and t['scheduled_time'])]

    # Sort algorithm tasks by score descending (Greedy choice)
    sorted_algorithm_tasks = sorted(algorithm_tasks, key=lambda x: x['score'], reverse=True)

    # Sort manually scheduled tasks by date and time to ensure correct placement
    manually_scheduled_tasks.sort(key=lambda x: (x['scheduled_date'], x['scheduled_time']))

    # Fetch user-specific availability
    user_availability = conn.execute('SELECT * FROM availability WHERE user_id = ?', (user_id,)).fetchall()
    availability_map = {avail['day_of_week']: {'start': avail['start_hour'], 'end': avail['end_hour']} for avail in user_availability}
    conn.close() # Close connection after fetching all necessary data
    
    # Diary Configuration
    
    organized_schedule = {}
    current_date = datetime.now()
    current_time_float = current_date.hour + current_date.minute / 60
    
    # Initialize the task pointer outside the loop so tasks are consumed across the week
    current_algorithm_task_index = 0
    
    # Helper for time formatting
    base_datetime_today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)

    # Plan for the next 7 days
    for day_offset in range(7):
        date_obj = current_date + timedelta(days=day_offset)
        date_str = date_obj.strftime('%Y-%m-%d')
        day_name_full = date_obj.strftime('%A') # e.g., 'Monday'
        day_name_display = date_obj.strftime('%A, %b %d')
        full_day_display = f"{day_name_display} ({date_str})"

        # Determine work hours for the current day based on user availability
        day_config = availability_map.get(day_name_full)
        if day_config:
            day_start_hour = day_config['start']
            day_end_hour = day_config['end']
            if day_end_hour <= day_start_hour: # Handle overnight shifts, e.g., 22:00 - 06:00
                day_end_hour += 24 # Treat as next day's hours for calculation
            day_total_available_hours = day_end_hour - day_start_hour
        else:
            # Default to standard human hours (8 AM - 10 PM) if no specific availability is set
            day_start_hour = 8
            day_end_hour = 22
            day_total_available_hours = day_end_hour - day_start_hour
        
        # Apply Hard Stop for Sleep (Sunset Parameter)
        day_end_hour = min(day_end_hour, 24 - WIND_DOWN_BUFFER_HOURS)
        day_total_available_hours = day_end_hour - day_start_hour # Recalculate after hard stop
        
        # Determine the actual start time for scheduling (don't schedule in the past for today)
        actual_start = float(day_start_hour)
        if day_offset == 0:
            actual_start = max(actual_start, current_time_float)

        # Initialize free blocks for the day based on availability and current time
        free_blocks = [{'start': actual_start, 'end': float(day_end_hour)}] if day_end_hour > actual_start else []

        big_tasks_scheduled_today = 0
        day_tasks = []
        hours_used_for_display = 0 # Track total hours scheduled for display

        # 1. Place manually scheduled tasks first
        for manual_task in manually_scheduled_tasks[:]: # Iterate over a copy to allow removal
            if manual_task['scheduled_date'] == date_str:
                # Convert scheduled_time (HH:MM) to minutes from midnight
                scheduled_time_parts = manual_task['scheduled_time'].split(':')
                manual_task_start_float = int(scheduled_time_parts[0]) + int(scheduled_time_parts[1]) / 60
                manual_task_end_float = manual_task_start_float + manual_task['duration']
                
                # Determine dynamic break based on task duration
                if manual_task['duration'] >= 3:
                    dynamic_break = 1.0  # 1 hour
                elif manual_task['duration'] >= 2:
                    dynamic_break = 0.5  # 30 mins
                else:
                    dynamic_break = 0.25 # 15 mins (default)
                
                manual_task_end_with_break = manual_task_end_float + dynamic_break
                
                # Add break task after manual task
                if dynamic_break > 0:
                    break_start_time_float = manual_task_end_float
                    break_task = {
                        'id': None, # No ID for a break
                        'title': 'Break',
                        'duration': dynamic_break,
                        'scheduled_time_display': (base_datetime_today + timedelta(hours=break_start_time_float)).strftime("%I:%M %p"),
                        'is_break': True # Custom flag to identify breaks in template
                    }
                    day_tasks.append(break_task)

                # Check if manual task is a "big task" and if we've hit the limit
                if manual_task['duration'] >= BIG_TASK_THRESHOLD_HOURS:
                    big_tasks_scheduled_today += 1

                # Update free blocks by subtracting the manual task
                new_free_blocks = []
                for block in free_blocks:
                    # Block is entirely before task
                    if block['end'] <= manual_task_start_float:
                        new_free_blocks.append(block)
                    # Block is entirely after task
                    elif block['start'] >= manual_task_end_with_break:
                        new_free_blocks.append(block)
                    # Task is inside block, splits it
                    elif block['start'] < manual_task_start_float and block['end'] > manual_task_end_with_break:
                        new_free_blocks.append({'start': block['start'], 'end': manual_task_start_float})
                        new_free_blocks.append({'start': manual_task_end_with_break, 'end': block['end']})
                    # Task overlaps start of block
                    elif block['start'] < manual_task_end_with_break and block['end'] > manual_task_end_with_break and block['start'] >= manual_task_start_float:
                        new_free_blocks.append({'start': manual_task_end_with_break, 'end': block['end']})
                    # Task overlaps end of block
                    elif block['start'] < manual_task_start_float and block['end'] > manual_task_start_float and block['end'] <= manual_task_end_float:
                        new_free_blocks.append({'start': block['start'], 'end': manual_task_start_float})
                    # Task completely covers block - do nothing, block is removed

                # --- Subtract Social Media Hour ---
                social_media_block = {'start': SOCIAL_MEDIA_START_HOUR, 'end': SOCIAL_MEDIA_END_HOUR}
                temp_blocks = []
                for block in new_free_blocks:
                    if block['end'] <= social_media_block['start'] or block['start'] >= social_media_block['end']:
                        temp_blocks.append(block)
                    elif block['start'] < social_media_block['start'] and block['end'] > social_media_block['end']:
                        temp_blocks.append({'start': block['start'], 'end': social_media_block['start']})
                        temp_blocks.append({'start': social_media_block['end'], 'end': block['end']})
                    elif block['start'] < social_media_block['end'] and block['end'] > social_media_block['end'] and block['start'] >= social_media_block['start']:
                        temp_blocks.append({'start': social_media_block['end'], 'end': block['end']})
                    elif block['start'] < social_media_block['start'] and block['end'] > social_media_block['start'] and block['end'] <= social_media_block['end']:
                        temp_blocks.append({'start': block['start'], 'end': social_media_block['start']})
                new_free_blocks = temp_blocks
                    
                free_blocks = sorted([b for b in new_free_blocks if b['end'] > b['start']], key=lambda x: x['start'])

                manual_task['scheduled_time_display'] = (base_datetime_today + timedelta(hours=manual_task_start_float)).strftime("%I:%M %p")
                day_tasks.append(manual_task)
                hours_used_for_display += manual_task['duration']
                
                manually_scheduled_tasks.remove(manual_task) # Remove from list once placed

        # Sort day_tasks to ensure manual tasks are displayed in chronological order
        day_tasks.sort(key=lambda x: datetime.strptime(x.get('scheduled_time_display', '12:00 AM'), "%I:%M %p"))

        # 2. Fill remaining time with algorithm-scheduled tasks into free blocks
        current_free_block_index = 0

        while current_algorithm_task_index < len(sorted_algorithm_tasks) and current_free_block_index < len(free_blocks):
            task = sorted_algorithm_tasks[current_algorithm_task_index]
            current_block = free_blocks[current_free_block_index]
            
            available_in_block = current_block['end'] - current_block['start']
            
            # --- Rule of 3: Check Big Task Limit ---
            if task['duration'] >= BIG_TASK_THRESHOLD_HOURS and big_tasks_scheduled_today >= MAX_BIG_TASKS_PER_DAY:
                current_algorithm_task_index += 1 # Skip this big task for today
                continue


            if available_in_block <= 0:
                current_free_block_index += 1
                continue

            if task['duration'] <= available_in_block:
                # Task fits completely
                task_start_time_float = current_block['start']
                task['scheduled_time_display'] = (base_datetime_today + timedelta(hours=task_start_time_float)).strftime("%I:%M %p")
                
                day_tasks.append(task)
                hours_used_for_display += task['duration']
                # Increment big task counter if applicable
                if task['duration'] >= BIG_TASK_THRESHOLD_HOURS:
                    big_tasks_scheduled_today += 1
                
                # Determine dynamic break
                if task['duration'] >= 3:
                    dynamic_break = 1.0
                elif task['duration'] >= 2:
                    dynamic_break = 0.5
                else:
                    dynamic_break = 0.25

                # Update the free block
                current_block['start'] += task['duration'] + dynamic_break
                
                current_algorithm_task_index += 1 # Move to next algorithm task
            else:
                # Task is too long, split it across days
                # The atomization already handled splitting into chunks.
                # If a chunk doesn't fit, it means the current block is too small for even a chunk.
                # This scenario should be less common with atomization, but the existing split logic
                # for remaining_hours will still apply if a chunk is larger than the available block.
                # The task-spanning logic already handles this by updating 'task' and moving to the next block/day.
                
                # The existing task-spanning logic handles this:
                # It schedules 'available_in_block' hours of the current task
                # and updates the task's remaining duration.
                
                # Schedule the part that fits
                part_to_schedule_duration = available_in_block
                
                scheduled_part = task.copy()
                scheduled_part['duration'] = part_to_schedule_duration
                scheduled_part['scheduled_time_display'] = (base_datetime_today + timedelta(hours=current_block['start'])).strftime("%I:%M %p")
                
                day_tasks.append(scheduled_part)
                hours_used_for_display += part_to_schedule_duration
                
                # Update the original task for the next iteration/day
                task['duration'] -= part_to_schedule_duration
                # No need to change title here, atomization already added (Part X)
                
                # Increment big task counter if applicable for the scheduled part
                if part_to_schedule_duration >= BIG_TASK_THRESHOLD_HOURS:
                    big_tasks_scheduled_today += 1

                # Current free block is now fully used
                current_free_block_index += 1 # Move to next free block
                # Do not increment current_algorithm_task_index; the remainder stays for the next day/block
        
        if day_tasks:
            # Re-sort day_tasks to ensure all tasks (manual and algo) are chronological
            day_tasks.sort(key=lambda x: datetime.strptime(x.get('scheduled_time_display', '12:00 AM'), "%I:%M %p"))

            organized_schedule[full_day_display] = {
                'tasks': day_tasks,
                'hours_used': hours_used_for_display,
                'progress': int((hours_used_for_display / day_total_available_hours) * 100) if day_total_available_hours > 0 else 0
            }

    return organized_schedule