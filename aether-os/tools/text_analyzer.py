"""text_analyzer — Word count, readability, keywords, and sentence stats."""
from __future__ import annotations
import re, math, logging
from collections import Counter

logger = logging.getLogger(__name__)

_STOP_WORDS = {
    "a","an","the","and","or","but","in","on","at","to","for","of","with",
    "by","from","is","are","was","were","be","been","being","have","has","had",
    "do","does","did","will","would","could","should","may","might","shall",
    "it","its","this","that","these","those","i","you","he","she","we","they",
    "me","him","her","us","them","my","your","his","our","their","what","which",
    "who","not","so","if","as","up","out","about","into","than","then","there",
}

def text_analyzer(text: str, action: str = "all") -> str:
    """
    Analyze a piece of text.

    Actions:
        all        : Run all analyses.
        count      : Word, sentence, paragraph, character counts.
        keywords   : Top 15 most frequent meaningful words.
        readability: Flesch reading-ease score and grade level.
        sentiment  : Simple positive/negative/neutral polarity.
        summary    : First and last sentence of each paragraph.
    """
    if not text or not isinstance(text, str):
        return "Error: text must be a non-empty string."

    action = (action or "all").strip().lower()
    words_raw = re.findall(r"\b[a-zA-Z']+\b", text)
    words = [w.lower() for w in words_raw]
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chars = len(text)

    def count_stats():
        return (
            f"Characters : {chars}\n"
            f"Words      : {len(words)}\n"
            f"Sentences  : {len(sentences)}\n"
            f"Paragraphs : {len(paragraphs)}\n"
            f"Avg words/sentence: {len(words)/max(len(sentences),1):.1f}"
        )

    def keywords():
        meaningful = [w for w in words if w not in _STOP_WORDS and len(w) > 2]
        top = Counter(meaningful).most_common(15)
        if not top:
            return "No keywords found."
        return "Top keywords:\n" + "\n".join(f"  {w:20s} {c}x" for w, c in top)

    def readability():
        syllables = sum(_syllable_count(w) for w in words)
        num_words = max(len(words), 1)
        num_sents = max(len(sentences), 1)
        asl = num_words / num_sents          # avg sentence length
        asw = syllables / num_words          # avg syllables per word
        fre = 206.835 - 1.015 * asl - 84.6 * asw
        fre = max(0, min(100, fre))
        if fre >= 90: grade = "5th grade (Very Easy)"
        elif fre >= 70: grade = "7th grade (Easy)"
        elif fre >= 60: grade = "8-9th grade (Standard)"
        elif fre >= 50: grade = "10-12th grade (Fairly Hard)"
        elif fre >= 30: grade = "College (Hard)"
        else: grade = "Professional (Very Hard)"
        return f"Flesch Reading Ease: {fre:.1f}/100\nGrade Level: {grade}"

    def sentiment():
        pos_words = {"good","great","excellent","amazing","wonderful","fantastic",
                     "love","best","better","happy","positive","success","win",
                     "perfect","brilliant","outstanding","superb","awesome","stellar"}
        neg_words = {"bad","terrible","awful","horrible","worst","hate","failure",
                     "poor","negative","wrong","error","broken","fail","issue",
                     "problem","difficult","hard","impossible","never","not"}
        pos = sum(1 for w in words if w in pos_words)
        neg = sum(1 for w in words if w in neg_words)
        if pos > neg * 1.5:    polarity = "Positive 😊"
        elif neg > pos * 1.5:  polarity = "Negative 😞"
        else:                   polarity = "Neutral 😐"
        return f"Sentiment : {polarity}\nPositive words: {pos}  |  Negative words: {neg}"

    def summary():
        out = []
        for i, para in enumerate(paragraphs[:5], 1):
            sents = [s.strip() for s in re.split(r"[.!?]+", para) if s.strip()]
            first = sents[0] if sents else ""
            last  = sents[-1] if len(sents) > 1 else ""
            out.append(f"Para {i}: {first}" + (f"  ...  {last}" if last else ""))
        return "Summary:\n" + "\n".join(out)

    if action == "count":       return count_stats()
    if action == "keywords":    return keywords()
    if action == "readability": return readability()
    if action == "sentiment":   return sentiment()
    if action == "summary":     return summary()
    if action == "all":
        return "\n\n".join([count_stats(), keywords(), readability(), sentiment()])

    return f"Unknown action '{action}'. Use: all, count, keywords, readability, sentiment, summary."

def _syllable_count(word: str) -> int:
    word = word.lower()
    count = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)
