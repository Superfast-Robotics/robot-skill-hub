"""Opt-in bounded lexical task ranking; task-lexical-v1.json is the frozen spec."""
import re

VERSION = "task_lexical_v1"
SPEC_SHA256 = "b40a2f135e61da7dcf34117cf5160bcf44d0d2f6891b0941623a39ff870e0612"
CANDIDATE_SPEC_SHA256 = "416b34c406d98238097806e1d02bff5c3e691f50f3125c23c762def7203d0e95"
LIMIT = 512
STOP = set("a an the and or to of for from with by in on at as is are be been being was were it its this that these those i me my we our you your please find show help need want use using".split())
WEIGHTS = {"id": 8, "name": 8, "aliases": 8, "capabilities": 6, "robots": 5, "framework": 5, "summary": 2}


class TaskQueryError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def stem(word):
    original = word
    if not re.fullmatch("[a-z]{5,}", word) or word in ("astar", "dstar", "rrtstar"):
        return word
    for suffix in ("ies", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3 and not (suffix == "s" and word.endswith("ss")):
            word = word[:-len(suffix)]
            if suffix == "ing" and len(word) >= 2 and word[-1] == word[-2] and word[-1] in "bdfgmnprt":
                word = word[:-1]
            break
    for suffix in ("ion", "ment"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[:-len(suffix)]
            break
    if len(word) >= 5 and word[-1] in "ey":
        word = word[:-1]
    assert word and original.startswith(word)
    return word


def terms(query, tokenize):
    if not isinstance(query, str) or len(query) > 240:
        raise TaskQueryError("invalid_task_query", "Task queries must be strings of at most 240 characters.")
    if not query.isascii():
        raise TaskQueryError("unsupported_task_query", "Task mode supports ASCII English queries; use all_terms for Unicode queries.")
    result = list(dict.fromkeys(stem(token) for token in tokenize(query) if token not in STOP))
    if len(result) > 16:
        raise TaskQueryError("invalid_task_query", "Task queries support at most 16 distinct content terms; narrow the query.")
    return result


def words(value):
    return re.findall(r"[^\W_]+", str(value).lower())


def fields(record):
    combinations = record.get("compatibility", [])
    if isinstance(combinations, dict):
        combinations = [combinations]
    combinations = [item for item in combinations or [] if isinstance(item, dict)]
    runtimes = list(dict.fromkeys(c.get("runtime") for c in combinations if c.get("runtime") not in (None, "", "unknown")))
    robots = record.get("robots") or list(dict.fromkeys(c.get("robot") for c in combinations if c.get("robot") not in (None, "", "unknown")))
    return {"id": [record["id"]], "name": [record.get("name", "")], "summary": [record.get("summary", "")],
            "aliases": record.get("aliases") or [], "capabilities": record.get("capabilities") or [], "robots": robots,
            "framework": [record.get("framework") or (runtimes[0] if len(runtimes) == 1 else "unknown")]}


def score(record, query_terms):
    tokenized = {key: [words(value) for value in values] for key, values in fields(record).items()}
    matched, unmatched, score_value, anchored = [], [], 0, False
    for term in query_terms:
        best, exact = 0, False
        for field, groups in tokenized.items():
            found = [word for group in groups for word in group if word.startswith(term)]
            if found and WEIGHTS[field] > best:
                best, exact = WEIGHTS[field], any(stem(word) == term for word in found)
            elif found and WEIGHTS[field] == best:
                exact = exact or any(stem(word) == term for word in found)
        if best:
            matched.append(term)
            score_value += best + int(exact)
            anchored = anchored or best >= 5
        else:
            unmatched.append(term)
    if not query_terms or len(matched) < min(2, len(query_terms)) or not anchored:
        return None
    phrase = False
    for key in ("name", "aliases"):
        for group in tokenized[key]:
            normalized = [stem(word) for word in group if word not in STOP]
            phrase = phrase or any(normalized[i:i + len(query_terms)] == query_terms for i in range(len(normalized) - len(query_terms) + 1))
    return {"model": VERSION, "score": score_value + 12 * int(phrase) - len(unmatched), "matched_terms": matched, "unmatched_terms": unmatched}


def rank(candidates, query, query_terms):
    if len(candidates) > LIMIT:
        raise TaskQueryError("query_too_broad", "Task ranking exceeds 512 hard-filtered records; narrow runtime, robot or other environment filters. More query text does not reduce this bound.")
    result = [(record, score(record, query_terms)) for record in candidates]
    result = [(record, match) for record, match in result if match is not None]
    result.sort(key=lambda item: (item[0]["id"] != query.lower(), -item[1]["score"], item[0].get("kind") != "preparation_recipe", item[0]["id"]))
    return result


def metadata(query_terms, count):
    return {"query_mode": "task", "search_semantics": VERSION, "query_terms": query_terms,
            "candidate_scope": "hard_filtered_records", "candidate_count": count, "candidate_limit": LIMIT}
