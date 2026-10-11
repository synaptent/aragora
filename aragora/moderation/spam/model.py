"""
Naive Bayes classifier for spam detection.

Provides the ML model used for statistical spam classification
with online learning support, thread-safe training, and
JSON-based model persistence.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
from collections import Counter

logger = logging.getLogger(__name__)


class NaiveBayesClassifier:
    """Simple Naive Bayes classifier for spam detection."""

    def __init__(self):
        """Initialize classifier."""
        self.word_spam_counts: Counter = Counter()
        self.word_ham_counts: Counter = Counter()
        self.spam_count: int = 0
        self.ham_count: int = 0
        self.vocabulary: set[str] = set()
        self._lock = threading.Lock()

    def train(self, text: str, is_spam: bool) -> None:
        """Train on a single example."""
        words = self._tokenize(text)

        with self._lock:
            if is_spam:
                self.spam_count += 1
                self.word_spam_counts.update(words)
            else:
                self.ham_count += 1
                self.word_ham_counts.update(words)
            self.vocabulary.update(words)

    def predict(self, text: str) -> tuple[bool, float]:
        """
        Predict if text is spam.

        Returns:
            Tuple of (is_spam, confidence)
        """
        words = self._tokenize(text)

        with self._lock:
            if self.spam_count == 0 and self.ham_count == 0:
                return False, 0.5

            total = self.spam_count + self.ham_count
            vocab_size = len(self.vocabulary) + 1

            # Log probabilities with Laplace smoothing
            log_prob_spam = math.log((self.spam_count + 1) / (total + 2))
            log_prob_ham = math.log((self.ham_count + 1) / (total + 2))

            for word in words:
                # P(word | spam)
                spam_word_prob = (self.word_spam_counts.get(word, 0) + 1) / (
                    self.spam_count + vocab_size
                )
                log_prob_spam += math.log(spam_word_prob)

                # P(word | ham)
                ham_word_prob = (self.word_ham_counts.get(word, 0) + 1) / (
                    self.ham_count + vocab_size
                )
                log_prob_ham += math.log(ham_word_prob)

            # Convert to probabilities
            max_log = max(log_prob_spam, log_prob_ham)
            prob_spam = math.exp(log_prob_spam - max_log)
            prob_ham = math.exp(log_prob_ham - max_log)
            total_prob = prob_spam + prob_ham

            spam_probability = prob_spam / total_prob

            is_spam = spam_probability > 0.5
            confidence = abs(spam_probability - 0.5) * 2  # 0 to 1

            return is_spam, confidence

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into words."""
        text = text.lower()
        # Simple word tokenization
        words = re.findall(r"\b[a-z]{2,15}\b", text)
        return words

    def save(self, path: str) -> None:
        """Save model to file using JSON (safe serialization)."""
        with self._lock:
            data = {
                "word_spam_counts": dict(self.word_spam_counts),
                "word_ham_counts": dict(self.word_ham_counts),
                "spam_count": self.spam_count,
                "ham_count": self.ham_count,
                "vocabulary": list(self.vocabulary),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)

    def load(self, path: str) -> bool:
        """Load model from JSON file.

        SECURITY: Only JSON format supported. Legacy pickle format no longer accepted.
        If you have old pickle models, use the migration script or recreate the model.
        """
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Invalid JSON model file %s: %s", path, e)
            return False
        except FileNotFoundError:
            logger.warning("Model file not found: %s", path)
            return False
        except OSError as e:
            logger.warning("Failed to load model: %s", e)
            return False

        try:
            self._apply_model_data(data)
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Invalid model data in %s: %s", path, e)
            return False
        return True

    def _apply_model_data(self, data: dict) -> None:
        """Apply loaded model data to instance."""
        word_spam_counts = Counter(data["word_spam_counts"])
        word_ham_counts = Counter(data["word_ham_counts"])
        spam_count = data["spam_count"]
        ham_count = data["ham_count"]
        vocabulary = set(data["vocabulary"])

        with self._lock:
            self.word_spam_counts = word_spam_counts
            self.word_ham_counts = word_ham_counts
            self.spam_count = spam_count
            self.ham_count = ham_count
            self.vocabulary = vocabulary

    @property
    def is_trained(self) -> bool:
        """Check if model has been trained."""
        return self.spam_count > 0 or self.ham_count > 0
