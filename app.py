import streamlit as st
import requests
from collections import Counter

st.set_page_config(page_title="🎬 나와 어울리는 영화는?", page_icon="🎬", layout="centered")

# -----------------------------
# TMDB 설정
# -----------------------------
TMDB_DISCOVER_URL = "https://api.themoviedb.org/3/discover/movie"
POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"

GENRE_ID = {
    "액션/어드벤처": 28,   # 액션
    "코미디": 35,         # 코미디
    "로맨스/드라마": None, # 아래에서 드라마/로맨스로 분기
    "SF/판타지": None,     # 아래에서 SF/판타지로 분기
}

SUBGENRE_ID = {
    "드라마": 18,
    "로맨스": 10749,
    "SF": 878,
    "판타지": 14,
}


# -----------------------------
# 사이드바: API 키 입력
# -----------------------------
st.sidebar.header("🔑 TMDB 설정")
api_key = st.sidebar.text_input("TMDB API Key", type="password")
st.sidebar.caption("TMDB에서 발급받은 API Key를 입력하면 추천 영화가 표시돼요.")

# -----------------------------
# 앱 UI
# -----------------------------
st.title("🎬 나와 어울리는 영화는?")
st.write("5개의 질문에 답하면, 당신의 취향에 맞는 장르를 분석하고 TMDB 인기 영화 5편을 추천해줘요!")

# -----------------------------
# 질문 데이터(각 옵션에 4분류 장르 매핑)
# -----------------------------
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


# -----------------------------
# 설문 렌더링
# -----------------------------
answers_top = []  # 4분류 장르 저장 (로맨스/드라마, 액션/어드벤처, SF/판타지, 코미디)

for q in questions:
    label_choices = [f"{text} ({genre})" for text, genre in q["choices"]]
    selection = st.radio(q["text"], label_choices, index=None, key=q["key"])

    if selection is None:
        answers_top.append(None)
    else:
        picked_genre = selection.split("(")[-1].replace(")", "").strip()
        answers_top.append(picked_genre)

st.divider()

# -----------------------------
# 분석: 최다 선택 장르 -> TMDB 장르 ID 결정
# -----------------------------
def decide_genre_id(answers: list[str]) -> tuple[str, int, str]:
    """
    return: (결정된_설명용_장르명, tmdb_genre_id, 추천_이유)
    """
    counts = Counter([a for a in answers if a is not None])
    top = counts.most_common(1)[0][0]  # 4분류 장르

    reason_map = {
        "로맨스/드라마": "감정선과 공감되는 이야기, 성장 서사를 선호하는 선택이 많았어요.",
        "액션/어드벤처": "도전적이고 속도감 있는 전개를 좋아하는 선택이 많았어요.",
        "SF/판타지": "상상력 넘치는 세계관과 몰입감을 중시하는 선택이 많았어요.",
        "코미디": "가볍게 웃고 스트레스를 푸는 분위기를 선호하는 선택이 많았어요.",
    }

    # 복합 장르 분기(간단 규칙: 기본값 고정)
    if top == "로맨스/드라마":
        final = "드라마"   # 기본값: 드라마
        gid = SUBGENRE_ID["드라마"]
    elif top == "SF/판타지":
        final = "SF"       # 기본값: SF
        gid = SUBGENRE_ID["SF"]
    elif top == "액션/어드벤처":
        final = "액션"
        gid = GENRE_ID["액션/어드벤처"]
    else:
        final = "코미디"
        gid = GENRE_ID["코미디"]

    return final, gid, reason_map.get(top, "선택 패턴을 기반으로 추천했어요.")


# -----------------------------
# TMDB 호출
# -----------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_movies(api_key: str, genre_id: int, limit: int = 5):
    params = {
        "api_key": api_key,
        "with_genres": genre_id,
        "language": "ko-KR",
        "sort_by": "popularity.desc",
        "page": 1,
    }
    r = requests.get(TMDB_DISCOVER_URL, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("results", [])[:limit]


def render_movie(movie: dict, why: str):
    title = movie.get("title", "제목 없음")
    rating = movie.get("vote_average", 0.0)
    overview = movie.get("overview") or "줄거리 정보가 없습니다."
    poster_path = movie.get("poster_path")

    col1, col2 = st.columns([1, 2.2])
    with col1:
        if poster_path:
            st.image(POSTER_BASE_URL + poster_path, use_container_width=True)
        else:
            st.write("🖼️ 포스터 없음")
    with col2:
        st.subheader(title)
        st.write(f"⭐ 평점: **{rating:.1f}** / 10")
        st.write(overview)
        st.info(f"🎯 이 영화를 추천하는 이유: {why}")


# -----------------------------
# 결과 보기 버튼
# -----------------------------
if st.button("결과 보기", type="primary"):
    if not api_key:
        st.error("사이드바에 TMDB API Key를 입력해주세요.")
        st.stop()

    if any(a is None for a in answers_top):
        st.warning("5개 질문에 모두 답해야 결과를 볼 수 있어요!")
        st.stop()

    # 1) 분석
    final_genre_name, genre_id, top_reason = decide_genre_id(answers_top)

    # 2) TMDB 조회
    st.write("분석 중...")
    with st.spinner("TMDB에서 인기 영화를 가져오는 중..."):
        try:
            movies = fetch_movies(api_key, genre_id, limit=5)
        except requests.HTTPError as e:
            st.error(f"TMDB 요청 실패(HTTP 오류): {e}")
            st.stop()
        except requests.RequestException as e:
            st.error(f"TMDB 요청 실패(네트워크 오류): {e}")
            st.stop()

    # 3) 결과 출력
    st.markdown("## ✅ 결과")
    st.write(f"당신에게 어울리는 장르는 **{final_genre_name}** 쪽이에요!")
    st.caption(top_reason)

    st.markdown("## 🍿 추천 영화 5편")
    if not movies:
        st.warning("영화를 찾지 못했어요. 잠시 후 다시 시도해 주세요.")
    else:
        # 영화별 이유는 기본 이유 + 가벼운 변주
        for i, movie in enumerate(movies, start=1):
            rating = movie.get("vote_average", 0.0)
            extra = "평점도 좋은 편이라 만족도가 높아요." if rating >= 7 else "대중적으로 인기 많은 작품이라 접근하기 좋아요."
            why = f"{top_reason} {extra}"
            st.markdown(f"### {i}.")
            render_movie(movie, why)
            st.divider()
