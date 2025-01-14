from flask import Flask, request, jsonify, render_template
import requests
import openai

app = Flask(__name__)

# API 키 설정
GEMINI_API_KEY = ""
YOUTUBE_API_KEY = ""
NAVER_CLIENT_ID = ""
NAVER_CLIENT_SECRET = ""
openai.api_key = GEMINI_API_KEY

# 태그 저장용 리스트
user_tags = []

# LLM을 이용한 검색 쿼리 최적화
def refine_query_with_llm(user_query):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": f"Optimize this search query for YouTube: '{user_query}'"}
            ]
        )
        refined_query = response["choices"][0]["message"]["content"].strip()
        return refined_query
    except Exception as e:
        print(f"Error refining query: {e}")
        return user_query

# 콘텐츠 필터링 Agent
def filter_results_with_llm(query, results):
    try:
        filtered_results = []
        for result in results:
            content_title = result['snippet']['title']
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": f"Does this content closely relate to '{query}'? Content: '{content_title}'. Respond with 'Yes' or 'No'."}
                ]
            )
            relevance = response["choices"][0]["message"]["content"].strip()
            if relevance.lower() == "yes":
                filtered_results.append(result)
            if len(filtered_results) >= 15:  # 최대 15개 콘텐츠 제한
                break
        return filtered_results
    except Exception as e:
        print(f"Error filtering results: {e}")
        return results[:15]

# 네이버 검색 API 호출 함수
def search_naver(query):
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {
        "query": query,
        "display": 6  # 필요한 결과 수
    }
    response = requests.get("https://openapi.naver.com/v1/search/webkr.json", headers=headers, params=params)

    if response.status_code == 200:
        items = response.json().get("items", [])
        # 네이버 결과를 JSON 형태로 변환
        return [{"link": item["link"], "description": item["title"]} for item in items]
    else:
        print(f"Naver API Error: {response.status_code}")
        return []


# 검색 API
@app.route('/search', methods=['POST'])
def search():
    query = request.json.get('query')
    if not query:
        return jsonify({"error": "Query is required"}), 400

    # LLM으로 검색 쿼리 최적화
    refined_query = refine_query_with_llm(query)

    # 대화 메시지 생성
    llm_conversation = [
        {"role": "user", "content": f"사용자가 입력한 검색어: '{query}'"},
        {"role": "bot", "content": f"LLM이 최적화한 검색어: '{refined_query}'"}
    ]

    # YouTube API 호출
    youtube_api_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&maxResults=50&q={refined_query}&key={YOUTUBE_API_KEY}"
    youtube_response = requests.get(youtube_api_url)
    if youtube_response.status_code != 200:
        return jsonify({"error": "Failed to fetch data from YouTube API"}), 500

    youtube_videos = youtube_response.json().get("items", [])
    filtered_videos = filter_results_with_llm(query, youtube_videos)

    # 네이버 검색 API 호출
    naver_results = search_naver(query)
    # JSON 응답 반환
    return jsonify({
        "llm_conversation": llm_conversation,
        "youtube": filtered_videos,
        "naver": naver_results
    })
    # return jsonify({"youtube": filtered_videos, "naver": naver_results})

# 태그 추가 API
@app.route('/add-tag', methods=['POST'])
def add_tag():
    tag = request.json.get('tag')
    if not tag:
        return jsonify({"error": "Tag is required"}), 400
    if tag not in user_tags:
        user_tags.append(tag)
    return jsonify({"tags": user_tags})

# 태그 삭제 API
@app.route('/delete-tag', methods=['POST'])
def delete_tag():
    tag = request.json.get('tag')
    if tag in user_tags:
        user_tags.remove(tag)
    return jsonify({"tags": user_tags})

# 추천 API
@app.route('/recommend', methods=['GET'])
def recommend():
    recommendations = {}
    for tag in user_tags:
        # YouTube 추천
        refined_query = refine_query_with_llm(tag)
        youtube_api_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&maxResults=15&q={refined_query}&key={YOUTUBE_API_KEY}"
        youtube_results = requests.get(youtube_api_url).json().get("items", [])

        # 네이버 검색 추천
        naver_results = search_naver(tag)  # 네이버 결과 추가

        # 추천 결과 통합
        recommendations[tag] = youtube_results + naver_results

    # 콘솔에 데이터 확인
    print(recommendations)
    return jsonify({"tags": user_tags, "recommendations": recommendations})

# 메인 페이지
@app.route('/')
def home():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
