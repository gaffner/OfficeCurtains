import os
import csv
import logging
from datetime import datetime
import pandas as pd


class StatisticsManager:
    def __init__(self, stats_dir="stats"):
        self.stats_dir = stats_dir
        self._ensure_stats_directory()

    def _ensure_stats_directory(self):
        if not os.path.exists(self.stats_dir):
            os.makedirs(self.stats_dir)

    def get_all_stats(self):
        """
        Get statistics for all available days

        Returns:
            list: List of dictionaries containing date and statistics for each day
        """
        all_stats = []
        stats_files = sorted(os.listdir(self.stats_dir), reverse=True)  # Sort in reverse to show newest first

        for filename in stats_files:
            if filename.startswith('stats_') and filename.endswith('.csv'):
                date = filename[6:-4]  # Extract date from filename
                filepath = os.path.join(self.stats_dir, filename)
                try:
                    df = pd.read_csv(filepath)
                    formatted_date = datetime.strptime(date, '%Y-%m-%d').strftime('%A, %B %d, %Y')
                    all_stats.append({
                        'date': formatted_date,
                        'raw_date': date,
                        'stats': df.to_dict('records')
                    })
                except Exception as e:
                    logging.error(f"Error reading stats file {filename}: {e}")

        return all_stats

    def get_stats_filename(self):
        """Generate statistics filename based on current date"""
        return os.path.join(self.stats_dir, f"stats_{datetime.now().strftime('%Y-%m-%d')}.csv")

    def initialize_stats_file(self):
        """Initialize the daily statistics file if it doesn't exist"""
        filename = self.get_stats_filename()
        if not os.path.exists(filename):
            with open(filename, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['room_number', 'up', 'down', 'stop'])
            logging.info(f"Created new statistics file: {filename}")

    def update_stats(self, room_number, action):
        """
        Update statistics for a room and action

        Args:
            room_number (str): The room number
            action (str): The action performed ('up', 'down', or 'stop')
        """
        filename = self.get_stats_filename()
        self.initialize_stats_file()

        try:
            df = pd.read_csv(filename)
        except pd.errors.EmptyDataError:
            df = pd.DataFrame(columns=['room_number', 'up', 'down', 'stop'])

        # Check if room exists in stats
        if room_number in df['room_number'].values:
            df.loc[df['room_number'] == room_number, action] += 1
        else:
            new_row = {'room_number': room_number, 'up': 0, 'down': 0, 'stop': 0, action: 1}
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

        # Save updated stats
        df.to_csv(filename, index=False)
        logging.info(f"Updated statistics for room {room_number}, action: {action}")

    def get_daily_stats(self):
        """
        Get statistics for the current day

        Returns:
            list: List of dictionaries containing statistics for each room
        """
        filename = self.get_stats_filename()
        if not os.path.exists(filename):
            return []

        try:
            df = pd.read_csv(filename)
            return df.to_dict('records')
        except Exception as e:
            logging.error(f"Error reading statistics file: {e}")
            return []
            
    def get_room_count(self):
        """
        Count the number of unique rooms in today's statistics
        
        Returns:
            int: Number of unique rooms that used the curtain control today
        """
        filename = self.get_stats_filename()
        if not os.path.exists(filename):
            return 0
            
        try:
            df = pd.read_csv(filename)
            return len(df['room_number'].unique())
        except Exception as e:
            logging.error(f"Error counting rooms in statistics file: {e}")
            return 0