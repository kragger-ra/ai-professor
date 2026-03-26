# entity_id,timestamp,x,y,z,health,sneak,bow_spotted,sprint,isinfluid,onground,creative,flying
# 1,15622700,1429.9880224324068,95.9221226646525,-1497.6006153909748,19.166666,0,0,0,0,0,1,1

# D:\Pets\NetTyan\Python\NetTyanRepo\NetTyan\data\predictors\entity_id_data.csv

# remove description field and date created
# add mode survival field
# old
# entity_id,player,entity_type,description,date_created
# 1,1,minecraft:player,,2025-01-27T00:45:53.726880
# new
# entity_id,player,entity_type,mode
# 1,1,minecraft:player,survival

import os
from typing import Optional

import numpy as np
import pandas as pd


class DatasetFixer:
    def __init__(self, data_folder: str):
        self.data_folder = data_folder
        self.collected_data_path = os.path.join(data_folder, "collected_data.csv")
        self.entity_desc_path = os.path.join(data_folder, "entity_id_data.csv")
        self.fixed_data_path = os.path.join(data_folder, "train.csv")
        self.fixed_desc_path = os.path.join(data_folder, "entity_desc.csv")
        # Add new paths for competition files
        self.train_path = os.path.join(data_folder, "train.csv")
        self.test_data_path = os.path.join(data_folder, "test_data.csv")
        self.test_path = os.path.join(data_folder, "test.csv")
        self.submission_path = os.path.join(data_folder, "correct_submission.csv")
        self.kaggle_submission_path = os.path.join(data_folder, "kaggle_submission.csv")
        self.sample_submission_path = os.path.join(data_folder, "sample_submission.csv")

    def fix_column_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fix column names to match competition format"""
        rename_map = {"entity_id": "id", "X": "x", "Y": "y", "Z": "z"}
        return df.rename(columns=rename_map)

    def fix_entity_descriptions(self):
        """Fix entity descriptions file format"""
        if not os.path.exists(self.entity_desc_path):
            print(f"Entity description file not found: {self.entity_desc_path}")
            return

        df = pd.read_csv(self.entity_desc_path)

        # Keep only required columns
        required_cols = ["id", "player", "entity_type"]
        df = df[required_cols].rename(columns={"id": "id"})

        # Ensure proper values
        df["player"] = df["player"].astype(int)
        df["mode"] = "survival"

        # Save fixed file
        df.to_csv(self.fixed_desc_path, index=False)
        print(f"Fixed entity descriptions saved to: {self.fixed_desc_path}")

    def fix_collected_data(self):
        """Fix collected data file format"""
        if not os.path.exists(self.collected_data_path):
            print(f"Collected data file not found: {self.collected_data_path}")
            return

        df = pd.read_csv(self.collected_data_path)

        # Fix column names
        df = self.fix_column_names(df)

        # Ensure proper data types
        numeric_cols = ["x", "y", "z", "health"]
        bool_cols = [
            "sneak",
            "bow_spotted",
            "sprint",
            "isinfluid",
            "onground",
            "creative",
            "flying",
        ]

        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        for col in bool_cols:
            df[col] = df[col].astype(int)

        # Ensure timestamps are integers
        df["timestamp"] = df["timestamp"].astype("int64")

        # Save fixed file
        df.to_csv(self.fixed_data_path, index=False)
        print(f"Fixed collected data saved to: {self.fixed_data_path}")

    def split_dataset(self, test_size: float = 0.2, prediction_window: int = 100):
        """Split dataset into train, test_data and test files ensuring proper id separation"""
        if not os.path.exists(self.collected_data_path):
            print(f"Collected data file not found: {self.collected_data_path}")
            return

        # Read and sort data by timestamp
        df = pd.read_csv(self.collected_data_path)
        df = self.fix_column_names(df)
        df = df.sort_values(["id", "timestamp"])

        # Get unique entity IDs and split them
        unique_ids = df["id"].unique()
        n_test = max(1, int(len(unique_ids) * test_size))
        test_ids = np.random.choice(unique_ids, size=n_test, replace=False)
        train_ids = np.setdiff1d(unique_ids, test_ids)

        # Split data ensuring complete separation
        train_data = df[df["id"].isin(train_ids)]
        test_entity_data = df[df["id"].isin(test_ids)]

        # Process test data
        test_data = []
        test_targets = []

        for entity_id in test_ids:
            entity_df = test_entity_data[test_entity_data["id"] == entity_id]
            n_samples = len(entity_df)

            if n_samples >= prediction_window:
                # Split entity data into test_data and test
                test_data.append(entity_df.iloc[:-prediction_window])

                # Get prediction targets
                targets = entity_df.iloc[-prediction_window:][["id", "timestamp"]]
                test_targets.append(targets)

        # Combine all data
        test_data_df = pd.concat(test_data) if test_data else pd.DataFrame()
        test_df = pd.concat(test_targets) if test_targets else pd.DataFrame()

        # Save files
        if not train_data.empty:
            train_data.to_csv(self.train_path, index=False)
        if not test_data_df.empty:
            test_data_df.to_csv(self.test_data_path, index=False)
        if not test_df.empty:
            test_df.to_csv(self.test_path, index=False)

        print(f"Dataset split complete:")
        print(f"Train IDs: {sorted(train_ids)}")
        print(f"Test IDs: {sorted(test_ids)}")
        print(f"Train samples: {len(train_data)}")
        print(f"Test data samples: {len(test_data_df)}")
        print(f"Test prediction targets: {len(test_df)}")

        # After splitting, create correct submission
        self.create_correct_submission()

    def create_sample_submission(self):
        """Create sample submission with random coordinates"""
        if not os.path.exists(self.test_path):
            print("Test file not found. Run split_dataset first.")
            return

        test = pd.read_csv(self.test_path)

        # Create sample submission with same IDs as test
        sample = pd.DataFrame()
        sample["ID"] = test.apply(
            lambda row: f"{int(row['id'])}_{int(row['timestamp'])}", axis=1
        )

        # Generate random coordinates in reasonable ranges
        sample["x"] = np.random.uniform(-100, 100, len(test))
        sample["y"] = np.random.uniform(0, 256, len(test))  # Minecraft height range
        sample["z"] = np.random.uniform(-100, 100, len(test))

        sample.to_csv(self.sample_submission_path, index=False)
        print(
            f"Created sample submission with random coordinates: {self.sample_submission_path}"
        )

    def create_correct_submission(self):
        """Create submission files:
        1. correct_submission.csv - Same as Kaggle format but without Usage column
        2. kaggle_submission.csv - With Usage column for competition
        """
        if not os.path.exists(self.test_path):
            print("Test file not found. Run split_dataset first.")
            return

        # Read data
        full_data = pd.read_csv(self.collected_data_path)
        full_data = self.fix_column_names(full_data)
        test = pd.read_csv(self.test_path)

        # Create submission base
        submission = pd.DataFrame()
        submission["ID"] = test.apply(
            lambda row: f"{int(row['id'])}_{int(row['timestamp'])}", axis=1
        )
        submission["x"] = np.nan
        submission["y"] = np.nan
        submission["z"] = np.nan

        # Fill coordinates from original data
        for idx, row in test.iterrows():
            matching_row = full_data[
                (full_data["id"] == row["id"])
                & (full_data["timestamp"] == row["timestamp"])
            ]
            if not matching_row.empty:
                for col in ["x", "y", "z"]:
                    submission.loc[idx, col] = matching_row[col].iloc[0]

        # Save correct submission (without Usage)
        submission.to_csv(self.submission_path, index=False)

        # Create and save Kaggle submission (with Usage)
        kaggle_submission = submission.copy()
        n_private = int(len(kaggle_submission) * 0.2)
        private_indices = np.random.choice(
            len(kaggle_submission), n_private, replace=False
        )
        kaggle_submission["Usage"] = "Public"
        kaggle_submission.loc[private_indices, "Usage"] = "Private"
        kaggle_submission.to_csv(self.kaggle_submission_path, index=False)

        print(f"Created submissions:")
        print(f"1. Correct format (without Usage): {self.submission_path}")
        print(f"2. Kaggle format (with Usage): {self.kaggle_submission_path}")
        print(f"Number of predictions: {len(submission)}")
        print(f"Public tests: {len(submission) - n_private}")
        print(f"Private tests: {n_private}")

        # After creating submissions, generate sample submission
        self.create_sample_submission()

    def fix_all(self):
        """Fix all dataset files and create competition splits"""
        self.fix_entity_descriptions()
        self.fix_collected_data()
        self.split_dataset()


def fix_dataset(data_folder: str, split: bool = True):
    """Helper function to fix dataset and optionally split it"""
    fixer = DatasetFixer(data_folder)
    if split:
        fixer.split_dataset()
        fixer.create_correct_submission()


if __name__ == "__main__":
    # Example usage with dataset splitting
    fix_dataset(
        r"D:\Pets\NetTyan\Python\NetTyanRepo\NetTyan\data\predictors", split=True
    )
