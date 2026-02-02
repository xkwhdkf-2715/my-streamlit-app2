import time
import requests
import streamlit as st
from collections import Counter
from typing import Dict, List, Optional, Tuple

# =============================
# Page
# =============================
st.set_page_config(page_title="🎬 나와 어울리는 영화는?", page_icon="🎬", layout="wide")

# =============================
# Constants
# =============================
TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_DISCOVER_URL = f"{TMDB_API_BASE}/discover/movie"
POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"

# 사용자 선택(4분류) -> TMDB with_genres 값
# TMDB Discover: with_genres는
# - "," 는 AND
# - "|" 는 OR
WITH_GENRES_MAP = {
    "로맨스/드라마": "10749|18",   # 로맨스 OR 드라마
    "액션/어드벤처": "28",
    "SF/판타지": "878|14",        # SF OR 판타지
    "코미디": "35",
}

GENRE_EMOJI = {
    "로맨스/드라마": "💘🎭",
    "액션/어드벤처": "🔥🧗",
    "SF/판타지": "🛸🧙‍♂️",
    "코미디": "🤣🎈",
}

# =============================
# Sidebar
# =============================
st.sidebar.header("🔑 TMDB 설정")
api_key = st.sidebar.text_input("TMDB API Key", type="password")
debug_mode = st.sidebar.toggle("디버그 모드(에러 원인 표시)", value=False)
st.sidebar.caption("TMDB에서 발급받은 API Key를 입력하면 추천 영화가 표시돼요.")

# =============================
# UI Header
# =============================
st.title("🎬 나와 어울리는 영화는?")
st.write("5개의 질문에 답하면, 당신의 취향에 맞는 장르를 분석하고 TMDB 인기 영화 5편을 예쁘게 추천해줘요!")

# =============================
# Questions
# =============================
questions = [
    {
        "key": "q1",
        "text": "Q1. 시험이 끝난 금요일 밤, 가장 끌리는 계획은?",
        "choices": [
            ("A. 조용한 카페나 방에서 음악 들으며 하루를 정리한다", "로맨스/드라마"),
            ("B. 친구들이랑 갑자기 여행이나 밤샘 드라이브를 떠난다", "액션/어드벤처"),
            ("C. 게임·영화 보면서 다른 세계에 푹 빠진다", "SF/판타지"),
            ("D. 술자리나 수다로 웃다가 하루를 마무리한다", "코미디"),
        ],
    },
    {
        "key": "q2",
        "text": "Q2. 과제가 너무 많을 때, 너의 대처법은?",
        "choices": [
            ("A. 힘들지만 의미를 찾으며 묵묵히 해낸다", "로맨스/드라마"),
            ("B. “일단 부딪혀 보자!” 하면서 단번에 몰아서 끝낸다", "액션/어드벤처"),
            ("C. 나만의 방식으로 효율 루트를 연구한다", "SF/판타지"),
            ("D. 투덜대면서도 친구랑 농담 주고받으며 한다", "코미디"),
        ],
    },
    {
        "key": "q3",
        "text": "Q3. 영화 속 주인공이 된다면, 어떤 캐릭터가 좋을까?",
        "choices": [
            ("A. 감정선이 깊고 성장 서사가 있는 인물", "로맨스/드라마"),
            ("B. 위험한 상황에서도 앞장서는 히어로 타입", "액션/어드벤처"),
            ("C. 특별한 능력이나 비밀을 가진 존재", "SF/판타지"),
            ("D. 어디서든 분위기 살리는 인간 비타민", "코미디"),
        ],
    },
    {
        "key": "q4",
        "text": "Q4. 친구가 “너 요즘 어떤 상태야?”라고 물어본다면?",
        "choices": [
            ("A. 생각할 게 많고 감정이 조금 복잡해", "로맨스/드라마"),
            ("B. 뭔가 새로운 걸 해보고 싶어서 들떠 있어", "액션/어드벤처"),
            ("C. 머릿속에서 이것저것 상상 중이야", "SF/판타지"),
            ("D. 그냥 웃고 떠들면서 살고 있어", "코미디"),
        ],
    },
    {
        "key": "q5",
        "text": "Q5. 영화에서 가장 중요하게 보는 요소는?",
        "choices": [
            ("A. 공감되는 감정과 현실적인 이야기", "로맨스/드라마"),
            ("B. 긴장감 넘치는 전개와 스케일", "액션/어드벤처"),
            ("C. 세계관 설정과 상상력", "SF/판타지"),
            ("D. 얼마나 많이 웃을 수 있느냐", "코미디"),
        ],
    },
]

# =============================
# Helpers
# =============================
def short_text(text: str, n: int = 95) -> str:
    text = (text or "").strip()
    if not text:
        return "짧은 소개(줄거리) 정보가 없습니다."
    return text if len(text) <= n else text[:n].rstrip() + "…"


def ensure_all_answered(picks: List[Optional[str]]) -> bool:
    return all(p is not None for p in picks)


def analyze_genre_weighted(picks: List[str]) -> Tuple[str, Dict[str, int], str]:
    """
    가중치 점수 + 동점 타이브레이크.
    """
    weights = [1, 1, 2, 2, 3]  # 뒤 문항 가중
    score = Counter()
    raw = Counter(picks)

    for i, g in enumerate(picks):
        score[g] += weights[i]

    best_score = max(score.values())
    candidates = [g for g, s in score.items() if s == best_score]

    if len(candidates) > 1:
        best_raw = max(raw[g] for g in candidates)
        candidates = [g for g in candidates if raw[g] == best_raw]

    # 마지막 동점은 고정 우선순위(원하는대로 조절 가능)
    priority = ["로맨스/드라마", "액션/어드벤처", "SF/판타지", "코미디"]
    final = sorted(candidates, key=lambda x: priority.index(x))[0]

    reason_map = {
        "로맨스/드라마": "감정선·공감·성장 서사를 중시하는 선택이 많았어요.",
        "액션/어드벤처": "속도감과 도전/모험 감성에 끌리는 선택이 많았어요.",
        "SF/판타지": "세계관·상상력·몰입을 중요하게 여기는 선택이 많았어요.",
        "코미디": "웃음과 가벼운 텐션으로 스트레스를 푸는 쪽을 선호해요.",
    }
    return final, dict(score), reason_map.get(final, "선택 패턴을 기반으로 추천했어요.")


def tmdb_request(
    url: str,
    params: dict,
    max_retries: int = 3,
    timeout: int = 15,
) -> Tuple[bool, Optional[dict], str, Optional[int]]:
    """
    TMDB 요청을 안전하게 수행.
    - 성공: (True, json, "", status_code)
    - 실패: (False, None, error_message, status_code)
    """
    backoff = 0.8
    last_error = ""
    last_status = None

    for _ in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            last_status = r.status_code

            if r.status_code == 429:
                last_error = "요청이 너무 많아요(429). 잠시 후 다시 시도해주세요."
                time.sleep(backoff)
                backoff *= 1.8
                continue

            if r.status_code in (401, 403):
                # 키/권한 문제
                # 응답 바디에 key 관련 정보가 있어도 노출 위험 줄이기 위해 메시지 간단화
                return False, None, "API Key가 유효하지 않거나 권한이 없어요(401/403).", r.status_code

            r.raise_for_status()
            return True, r.json(), "", r.status_code

        except requests.exceptions.Timeout:
            last_error = "TMDB 요청 시간이 초과됐어요(Timeout)."
        except requests.exceptions.ConnectionError:
            last_error = "네트워크 연결 오류가 발생했어요(ConnectionError)."
        except requests.exceptions.HTTPError:
            # 기타 HTTP 오류
            last_error = f"TMDB 서버 응답 오류(HTTP {last_status})."
        except requests.exceptions.RequestException as e:
            last_error = f"요청 오류: {type(e).__name__}"

        time.sleep(backoff)
        backoff *= 1.8

    return False, None, last_error or "TMDB 요청에 실패했어요.", last_status


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_discover_movies_success_only(api_key: str, with_genres: str, limit: int = 5) -> List[dict]:
    """
    성공 결과만 캐시에 담기도록:
    - 이 함수는 '성공' 케이스만 반환하도록 설계(실패는 밖에서 처리)
    """
    params = {
        "api_key": api_key,
        "with_genres": with_genres,
        "language": "ko-KR",
        "sort_by": "popularity.desc",
        "include_adult": "false",
        "include_video": "false",
        "page": 1,
        # 품질 필터(가끔 서버/지역에 따라 문제 생길 수 있어 폴백 전략도 함께 사용)
        "vote_count.gte": 100,
    }
    ok, data, err, status = tmdb_request(TMDB_DISCOVER_URL, params=params)
    if not ok or not data:
        # cache 함수 안에서는 예외를 던지면 redacted가 떠서,
        # 여기서는 "빈 리스트"를 반환하고 밖에서 폴백/에러 처리.
        return []
    return (data.get("results") or [])[:limit]


def fetch_discover_movies_with_fallback(api_key: str, with_genres: str, limit: int = 5) -> Tuple[List[dict], str]:
    """
    1차: 필터 포함(캐시됨)
    2차 폴백: 필터 제거(직접 호출, 실패 원인 메시지 확보)
    """
    movies = fetch_discover_movies_success_only(api_key, with_genres, limit=limit)
    if movies:
        return movies, ""

    # 폴백(필터 최소화)
    params2 = {
        "api_key": api_key,
        "with_genres": with_genres,
        "language": "ko-KR",
        "sort_by": "popularity.desc",
        "page": 1,
        "include_adult": "false",
        "include_video": "false",
    }
    ok2, data2, err2, status2 = tmdb_request(TMDB_DISCOVER_URL, params=params2)
    if not ok2:
        hint = err2
        if status2 == 401 or status2 == 403:
            hint += " (사이드바의 키를 다시 확인해 주세요)"
        return [], hint
    results = (data2.get("results") or [])[:limit]
    if not results:
        return [], "해당 장르에서 결과가 거의 없어요(검색 조건/언어 설정 영향일 수 있어요)."
    return results, ""


def render_movie_card(movie: dict, emoji: str, reason: str):
    title = movie.get("title") or "제목 없음"
    rating = float(movie.get("vote_average") or 0.0)
    poster_path = movie.get("poster_path")
    overview = short_text(movie.get("overview"), 95)

    with st.container(border=True):
        if poster_path:
            st.image(POSTER_BASE_URL + poster_path, use_container_width=True)
        else:
            st.write("🖼️ 포스터 없음")

        st.markdown(f"### {emoji} {title}")
        st.write(f"⭐ **{rating:.1f}** / 10")
        st.caption(overview)
        st.markdown(f"**추천 이유:** {reason}")


def build_reason(base_reason: str, movie: dict) -> str:
    rating = float(movie.get("vote_average") or 0.0)
    vote_count = int(movie.get("vote_count") or 0)
    extra = "평점/반응도 좋은 편이라 만족도가 높을 확률이 커요." if (rating >= 7.3 and vote_count >= 200) else "요즘 인기작이라 가볍게 즐기기 좋아요."
    text = f"{base_reason} {extra}"
    return text if len(text) <= 170 else text[:170].rstrip() + "…"


# =============================
# Survey (form)
# =============================
answers: List[Optional[str]] = []

with st.form("quiz_form"):
    for q in questions:
        labels = [f"{t} ({g})" for t, g in q["choices"]]
        picked = st.radio(q["text"], labels, index=None, key=q["key"])
        if picked is None:
            answers.append(None)
        else:
            answers.append(picked.split("(")[-1].replace(")", "").strip())

    submitted = st.form_submit_button("결과 보기", type="primary")

# =============================
# Results
# =============================
if submitted:
    if not api_key:
        st.error("사이드바에 TMDB API Key를 입력해주세요.")
        st.stop()

    if not ensure_all_answered(answers):
        st.warning("5개 질문에 모두 답해야 결과를 볼 수 있어요!")
        st.stop()

    picks = [a for a in answers if a is not None]
    top_genre, score_map, base_reason = analyze_genre_weighted(picks)
    emoji = GENRE_EMOJI.get(top_genre, "🎬")
    with_genres = WITH_GENRES_MAP[top_genre]

    # 로딩
    with st.spinner("분석 중... TMDB에서 인기 영화를 가져오는 중!"):
        movies, err_hint = fetch_discover_movies_with_fallback(api_key, with_genres, limit=5)

    if err_hint:
        st.error(f"TMDB 추천을 가져오지 못했어요: {err_hint}")
        if debug_mode:
            st.code(
                f"debug:\n"
                f"- top_genre: {top_genre}\n"
                f"- with_genres: {with_genres}\n"
                f"- score_map: {score_map}\n",
                language="text",
            )
        st.stop()

    if not movies:
        st.warning("추천 영화를 찾지 못했어요. 잠시 후 다시 시도해 주세요.")
        if debug_mode:
            st.code(
                f"debug:\n"
                f"- top_genre: {top_genre}\n"
                f"- with_genres: {with_genres}\n"
                f"- score_map: {score_map}\n",
                language="text",
            )
        st.stop()

    # 결과 타이틀
    st.markdown(f"# 당신에게 딱인 장르는: **{emoji} {top_genre}**!")
    st.caption(base_reason)
    st.write("")

    # 3열 카드 레이아웃
    cols = st.columns(3)
    for idx, movie in enumerate(movies):
        why = build_reason(base_reason, movie)
        with cols[idx % 3]:
            render_movie_card(movie, emoji, why)
