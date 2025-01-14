from flask import Flask, request, jsonify, render_template
import openai
import requests
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import os

app = Flask(__name__)

# Load API keys from .env file
load_dotenv()  # .env 파일 로드
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

if not OPENAI_API_KEY:
    print("[ERROR] OPENAI_API_KEY is not set. Check your .env file.")
if not YOUTUBE_API_KEY:
    print("[ERROR] YOUTUBE_API_KEY is not set. Check your .env file.")
if not NAVER_CLIENT_ID:
    print("[ERROR] NAVER_CLIENT_ID is not set. Check your .env file.")
if not NAVER_CLIENT_SECRET:
    print("[ERROR] NAVER_CLIENT_SECRET is not set. Check your .env file.")

# 태그 저장용 리스트
user_tags = []

# LLM을 이용한 검색 쿼리 최적화
def refine_query_with_llm(user_query):
    try:
        print(f"[INFO] Original query: {user_query}")
        response = openai.ChatCompletion.create(
            model="gpt-4",  # 기본적으로 gpt-4 사용
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": f"Optimize this search query for YouTube: '{user_query}'"}
            ]
        )
        refined_query = response['choices'][0]['message']['content'].strip()
        print(f"[INFO] Refined query: {refined_query}")
        return refined_query
    except Exception as e:
        print(f"[ERROR] Error refining query with gpt-4: {e}")
        print("[INFO] Falling back to gpt-3.5-turbo.")
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",  # 대체 모델
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": f"Optimize this search query for YouTube: '{user_query}'"}
                ]
            )
            refined_query = response['choices'][0]['message']['content'].strip()
            print(f"[INFO] Refined query using fallback model: {refined_query}")
            return refined_query
        except Exception as fallback_e:
            print(f"[ERROR] Error refining query with fallback model: {fallback_e}")
            return user_query  # 원본 쿼리 반환



# 콘텐츠 필터링 Agent
def filter_results_with_llm_parallel(query, results):
    def process_result(result):
        try:
            content_title = result['snippet']['title']
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": f"Does this content closely relate to '{query}'? Content: '{content_title}'."}
                ]
            )
            relevance = response['choices'][0]['message']['content'].strip().lower()
            return result if "yes" in relevance else None
        except Exception as e:
            print(f"[ERROR] Error processing result: {e}")
            return result  # 실패 시 기본적으로 포함

    filtered_results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_result, result) for result in results]
        for future in futures:
            processed_result = future.result()
            if processed_result:
                filtered_results.append(processed_result)
                if len(filtered_results) >= 15:
                    break
    return filtered_results



# 네이버 검색 API 호출 함수
def search_naver(query):
    try:
        headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
        }
        params = {
            "query": query,
            "display": 6
        }
        response = requests.get("https://openapi.naver.com/v1/search/webkr.json", headers=headers, params=params)
        if response.status_code == 200:
            print(f"[INFO] Naver API response: {response.json()}")  # 응답 로그
            items = response.json().get("items", [])
            return [{"link": item["link"], "description": item["title"]} for item in items]
        else:
            print(f"[ERROR] Naver API Error: {response.status_code}, {response.text}")  # 에러 로그
            return []
    except Exception as e:
        print(f"[ERROR] Exception during Naver API call: {e}")  # 예외 로그
        return []

# 호출
@app.route('/')
def home():
    return render_template('index.html')

# 검색 API
@app.route('/search', methods=['POST'])
def search():
    try:
        query = request.json.get('query')
        if not query:
            print("[ERROR] Query not provided in request.")
            return jsonify({"error": "Query is required"}), 400

        print(f"[INFO] Received search query: {query}")

        # LLM으로 검색 쿼리 최적화
        refined_query = refine_query_with_llm(query)

        # YouTube API 호출
        youtube_api_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&maxResults=50&q={refined_query}&key={YOUTUBE_API_KEY}"
        youtube_response = requests.get(youtube_api_url)
        if youtube_response.status_code != 200:
            print(f"[ERROR] YouTube API Error: {youtube_response.status_code}, {youtube_response.text}")
            return jsonify({"error": "Failed to fetch data from YouTube API"}), 500

        youtube_videos = youtube_response.json().get("items", [])
        print(f"[INFO] YouTube API returned {len(youtube_videos)} results.")

        # 병렬로 콘텐츠 필터링
        filtered_videos = filter_results_with_llm_parallel(query, youtube_videos)

        # 네이버 검색 API 호출
        naver_results = search_naver(query)
        print(f"[INFO] Naver API returned {len(naver_results)} results.")

        return jsonify({
            "youtube": filtered_videos,
            "naver": naver_results
        })
    except Exception as e:
        print(f"[ERROR] Exception in search endpoint: {e}")
        return jsonify({"error": "An unexpected error occurred."}), 500

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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
