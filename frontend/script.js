
// 현재 업로드된 app.py 기준 서버 포트는 5001입니다.
// 백엔드를 5000번 포트로 실행하도록 바꾸면 API_BASE_URL만 "http://localhost:5000/api"로 수정하세요.

"use strict";

   //0. 기본 설정
const API_BASE_URL = "http://localhost:5001/api";
const CAMPUS_ID = 1;
const DEFAULT_LAT = 36.6285;   // 충북대 메인캠퍼스 기본 좌표
const DEFAULT_LNG = 127.4568;
const NEARBY_RADIUS_M = 500;   // 현재위치 메시지 조회 반경

let messages = [];
let currentTab = "all";
let currentSort = "latest";
let selectedFile = null;
let selectedFilePreviewUrl = null;

let activeLoadSeq = 0;
let isSubmitting = false;

let map = null;
let userMarker = null;
let heatCircles = [];
let messageOverlays = [];
// 인기 메시지 말풍선 오버레이 관리
let messageBubbleOverlays = [];
let currentFeedMessages = [];
let selectedLocationGroup = null;

let userLat = DEFAULT_LAT;
let userLng = DEFAULT_LNG;

// 인기 메시지 기준 (좋아요 수 이상일 때 말풍선 표시)
const POPULAR_MESSAGE_LIKE_THRESHOLD = 1;

function $(id) {
  return document.getElementById(id);
}


   //1. device_id 관리
function getDeviceId() {
  let deviceId = localStorage.getItem("nowvibe_device_id");

  if (!deviceId) {
    deviceId =
      "device_" +
      Date.now() +
      "_" +
      Math.random().toString(36).slice(2, 10);

    localStorage.setItem("nowvibe_device_id", deviceId);
  }

  return deviceId;
}

const DEVICE_ID = getDeviceId();


   //2. 공통 API 함수
async function apiRequest(path, options = {}) {
  const url = `${API_BASE_URL}${path}`;

  const fetchOptions = {
    ...options,
    headers: {
      ...(options.headers || {}),
    },
  };

  // body가 있는 요청일 때만 JSON 헤더를 붙임
  // GET 요청에는 Content-Type을 붙이면 Flask가 빈 body를 JSON으로 파싱하려고 할 수 있음
  if (
    fetchOptions.body &&
    !(fetchOptions.body instanceof FormData) &&
    !fetchOptions.headers["Content-Type"]
  ) {
    fetchOptions.headers["Content-Type"] = "application/json";
  }

  const response = await fetch(url, fetchOptions);

  const responseText = await response.text();

  let result = null;

  try {
    result = responseText ? JSON.parse(responseText) : null;
  } catch (error) {
    console.error("JSON이 아닌 서버 응답:", responseText);
    throw new Error(
      `서버가 JSON이 아닌 응답을 보냈습니다. 상태 코드: ${response.status}`
    );
  }

  if (!response.ok || result?.status === "error") {
    const message =
      result?.message ||
      result?.error ||
      `요청 실패: ${response.status}`;

    const customError = new Error(message);
    customError.status = response.status;
    customError.payload = result;
    throw customError;
  }

  return result?.data;
}

function buildQuery(params) {
  const query = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.append(key, value);
    }
  });

  return query.toString();
}

function createLoadToken(tab) {
  activeLoadSeq += 1;

  return {
    tab,
    seq: activeLoadSeq,
  };
}

function isActiveLoad(token) {
  return currentTab === token.tab && activeLoadSeq === token.seq;
}


   //3. 초기 실행
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  initLocation();
  bindFormSubmit();
  renderFilterBar();
});



  // 4. 지도 / 위치 처리
function initMap() {
  const mapContainer = $("map");

  if (!mapContainer) return;

  if (!window.kakao || !window.kakao.maps) {
    console.warn("Kakao Maps SDK가 로드되지 않았습니다.");
    return;
  }

  const center = new kakao.maps.LatLng(userLat, userLng);

  map = new kakao.maps.Map(mapContainer, {
    center,
    level: 3,
  });

  setUserMarker(userLat, userLng);
}

function initLocation() {
  if (!navigator.geolocation) {
    console.warn("이 브라우저에서는 위치 정보를 사용할 수 없습니다.");
    loadTabData();
    return;
  }

  navigator.geolocation.getCurrentPosition(
    async (position) => {
      userLat = position.coords.latitude;
      userLng = position.coords.longitude;

      if (map) {
        const currentPosition = new kakao.maps.LatLng(userLat, userLng);
        map.setCenter(currentPosition);
      }

      setUserMarker(userLat, userLng);
      await recordUserLocation();
      await loadTabData();
    },
    async (error) => {
      console.warn("위치 조회 실패. 기본 캠퍼스 좌표로 실행합니다.", error);
      await loadTabData();
    },
    {
      enableHighAccuracy: true,
      timeout: 8000,
      maximumAge: 30000,
    }
  );
}

function setUserMarker(lat, lng) {
  if (!map || !window.kakao || !window.kakao.maps) return;

  const position = new kakao.maps.LatLng(lat, lng);

  if (userMarker) {
    userMarker.setPosition(position);
    return;
  }

  userMarker = new kakao.maps.Marker({
    position,
    map,
    title: "내 위치",
  });
}

async function recordUserLocation() {
  try {
    await apiRequest("/user/location", {
      method: "POST",
      body: JSON.stringify({
        device_id: DEVICE_ID,
        latitude: userLat,
        longitude: userLng,
      }),
    });
  } catch (error) {
    // 위치 기록은 실패해도 핵심 기능은 계속 사용 가능하게 둡니다.
    console.warn("위치 기록 실패:", error.message);
  }
}



   //5. 탭 / 정렬

async function switchTab(tab) {
  console.log(`[TAB] switchTab 호출: "${tab}" (이전: "${currentTab}")`);
  currentTab = tab;
  selectedLocationGroup = null;

  const tabs = ["all", "current", "history"];

  tabs.forEach((tabName) => {
    const tabButton = document.getElementById(`tab-${tabName}`);
    if (!tabButton) return;

    if (tabName === tab) {
      tabButton.className =
        "flex-1 py-4 text-center border-b-2 border-amber-400 text-amber-400 font-bold";
    } else {
      tabButton.className =
        "flex-1 py-4 text-center border-b-2 border-transparent text-gray-400 hover:text-gray-200";
    }
  });

  renderFilterBar();

  if (tab === "all") {
    await fetchMessages();
    return;
  }

  if (tab === "current") {
    await fetchNearbyMessages();
    return;
  }

  if (tab === "history") {
    await fetchUserHistory();
    return;
  }
}

function setSort(sort) {
  currentSort = sort;
  renderFilterBar();

  if (currentTab === "all") {
    fetchMessages();
  }
}

function renderFilterBar() {
  const filterBar = $("filter-bar");
  if (!filterBar) return;

  if (selectedLocationGroup && currentTab !== "history") {
    filterBar.innerHTML = `
      <span>선택한 위치의 메시지 ${selectedLocationGroup.messages.length}개</span>
      <button type="button" onclick="showAllMessages()" class="text-amber-400 font-semibold">
        전체 보기
      </button>
    `;
    return;
  }

  if (currentTab === "all") {
    filterBar.innerHTML = `
      <span>나우바이브 맵 피드</span>
      <div class="flex gap-3">
        <button
          type="button"
          onclick="setSort('latest')"
          class="${currentSort === "latest" ? "text-amber-400 font-semibold" : "hover:text-gray-200"}"
        >
          최신순
        </button>
        <button
          type="button"
          onclick="setSort('popular')"
          class="${currentSort === "popular" ? "text-amber-400 font-semibold" : "hover:text-gray-200"}"
        >
          인기순
        </button>
      </div>
    `;
    return;
  }

  if (currentTab === "current") {
    filterBar.innerHTML = `
      <span>반경 ${NEARBY_RADIUS_M}m 이내 현재위치 메시지</span>
      <button type="button" onclick="fetchNearbyMessages()" class="text-amber-400 font-semibold">
        새로고침
      </button>
    `;
    return;
  }

  if (currentTab === "history") {
    filterBar.innerHTML = `
      <span>오늘 내가 지나온 타임라인 동선</span>
      <button type="button" onclick="fetchUserHistory()" class="text-amber-400 font-semibold">
        새로고침
      </button>
    `;
  }
}

async function loadTabData() {
  if (currentTab === "all") {
    await fetchMessages();
    return;
  }

  if (currentTab === "current") {
    await fetchNearbyMessages();
    return;
  }

  if (currentTab === "history") {
    await fetchUserHistory();
  }
}



   //6. 메시지 조회

async function fetchMessages() {
  console.log(`[FETCH] fetchMessages 호출, currentTab: "${currentTab}"`);
  if (currentTab !== "all") {
    console.log(`[FETCH] fetchMessages 차단됨 (currentTab이 "all"이 아님)`);
    return;
  }

  const token = createLoadToken("all");

  showFeedLoading("메시지를 불러오는 중입니다...");

  try {
    const query = buildQuery({
      campus_id: CAMPUS_ID,
      page: 1,
      limit: 20,
      sort: currentSort,
      device_id: DEVICE_ID,
    });

    const data = await apiRequest(`/messages?${query}`);

    if (!isActiveLoad(token)) return;

    messages = normalizeMessages(data.messages || []);
    currentFeedMessages = messages;
    selectedLocationGroup = null;
    renderFilterBar();

    renderFeed(messages);
    updateHeatmap(messages);

  } catch (error) {
    if (!isActiveLoad(token)) return;

    console.error("메시지 조회 실패:", error);
    showFeedError(error.message || "메시지를 불러오지 못했습니다.");
  }
}

async function fetchNearbyMessages() {
  if (currentTab !== "current") return;

  const token = createLoadToken("current");

  showFeedLoading("현재 위치 주변 메시지를 불러오는 중입니다...");

  try {
    const query = buildQuery({
      campus_id: CAMPUS_ID,
      latitude: userLat,
      longitude: userLng,
      radius: NEARBY_RADIUS_M,
      device_id: DEVICE_ID,
    });

    const data = await apiRequest(`/messages/nearby?${query}`);

    if (!isActiveLoad(token)) return;

    const nearbyMessages = normalizeMessages(data.messages || []);
    currentFeedMessages = nearbyMessages;
    selectedLocationGroup = null;
    renderFilterBar();

    renderFeed(nearbyMessages);
    updateHeatmap(nearbyMessages);

  } catch (error) {
    if (!isActiveLoad(token)) return;

    console.error("현재 위치 메시지 조회 실패:", error);
    showFeedError(error.message || "현재 위치 메시지를 불러오지 못했습니다.");
  }
}

async function fetchUserHistory() {
  console.log(`[HISTORY] fetchUserHistory 호출, currentTab: "${currentTab}"`);
  if (currentTab !== "history") {
    console.log(`[HISTORY] fetchUserHistory 차단됨`);
    return;
  }

  const token = createLoadToken("history");

  showFeedLoading("동선 히스토리를 불러오는 중입니다...");

  try {
    const query = buildQuery({
      device_id: DEVICE_ID,
      limit: 50,
    });

    const data = await apiRequest(`/messages/history?${query}`);

    if (!isActiveLoad(token)) return;

    renderHistory(data.history || []);

  } catch (error) {
    if (!isActiveLoad(token)) return;

    console.error("히스토리 조회 실패:", error);
    renderHistory([]);
  }
}

function normalizeMessages(rawMessages) {
  return rawMessages.map((message) => ({
    id: message.id,
    text: message.text || "",
    location: message.location || message.location_name || "캠퍼스 안",
    latitude: Number(message.latitude),
    longitude: Number(message.longitude),
    likes: Number(message.likes ?? message.likes_count ?? 0),
    ttl: Number(message.ttl ?? 3),
    image: message.image || message.image_url || null,
    created_at: message.created_at || null,
    expires_at: message.expires_at || null,
    is_liked_by_user: Boolean(message.is_liked_by_user),
    campus_id: message.campus_id,
    distance_m: message.distance_m,
  }));
}



   //7. 메시지 렌더링

function renderFeed(feedMessages) {
  console.log(`[RENDER] renderFeed 호출, currentTab: "${currentTab}", 메시지 수: ${feedMessages?.length}`);
  if (currentTab === "history") {
    console.error("[BUG] renderFeed가 history 탭에서 호출됨! 스택 추적:");
    console.trace();
    return;
  }
  const container = $("feed-container");
  if (!container) return;

  container.innerHTML = "";

  if (!feedMessages || feedMessages.length === 0) {
    container.innerHTML = `
      <div class="text-center py-12 text-gray-500 text-sm">
        아직 공유된 바이브가 없습니다.
      </div>
    `;
    return;
  }

  feedMessages.forEach((message) => {
    const card = document.createElement("div");
    const isGhost = message.ttl !== 999 && message.ttl <= 3;

    card.className =
      `bg-gray-900 border border-gray-800 p-4 rounded-xl cursor-pointer hover:border-gray-700 transition-all ` +
      `${isGhost ? "ghost-message" : ""}`;

    card.innerHTML = `
      <div class="flex justify-between items-start mb-2">
        <div class="flex items-center gap-2">
          <span class="text-xs px-2 py-0.5 rounded bg-gray-800 text-amber-400 font-medium">
            익명
          </span>
          <span class="text-xs text-gray-500">
            <i class="fa-solid fa-location-dot text-[10px] text-gray-400 mr-1"></i>
            ${escapeHTML(message.location)}
          </span>
        </div>
        <span class="text-xs text-gray-500">${formatTime(message.created_at)}</span>
      </div>

      <p class="text-sm text-gray-200 leading-relaxed mb-3">
        ${escapeHTML(message.text)}
      </p>

      ${
        message.image
          ? `<img src="${escapeAttribute(message.image)}" alt="첨부 이미지" class="w-full h-32 object-cover rounded-lg mb-3 border border-gray-800">`
          : ""
      }

      <div class="flex justify-between items-center text-xs text-gray-500 pt-1 border-t border-gray-900">
        <span class="text-[10px] text-gray-400">
          <i class="fa-regular fa-clock mr-1"></i>
          ${formatTTL(message)}
        </span>

        <div class="flex gap-4">
          <button type="button" class="like-btn hover:text-amber-400 flex items-center gap-1 ${
            message.is_liked_by_user ? "text-amber-400" : ""
          }">
            <i class="${message.is_liked_by_user ? "fa-solid" : "fa-regular"} fa-heart"></i>
            <span>${message.likes}</span>
          </button>

          <button type="button" class="report-btn hover:text-red-400">
            <i class="fa-regular fa-flag"></i> 신고
          </button>
        </div>
      </div>
    `;

    card.addEventListener("click", () => {
      openMessageModal(message.id);
    });

    const likeButton = card.querySelector(".like-btn");
    likeButton.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleLike(message.id, message.is_liked_by_user);
    });

    const reportButton = card.querySelector(".report-btn");
    reportButton.addEventListener("click", (event) => {
      event.stopPropagation();
      reportMessage(message.id);
    });

    container.appendChild(card);
  });
}

function renderHistory(history) {
  const container = document.getElementById("feed-container");
  if (!container) return;

  if (!history || history.length === 0) {
    container.innerHTML = `
      <div class="p-4 border-l-2 border-amber-400 space-y-6 ml-2">
        <div class="relative">
          <span class="absolute -left-[21px] top-1 bg-amber-400 w-2.5 h-2.5 rounded-full"></span>
          <p class="text-xs text-gray-400">동선 기록 없음</p>
          <p class="text-sm font-semibold">아직 기록된 동선이 없습니다.</p>
          <p class="text-xs text-gray-500 mt-1">
            위치 권한을 허용하면 이곳에 이동 기록이 표시됩니다.
          </p>
        </div>
      </div>
    `;
    return;
  }

  const sortedHistory = [...history].sort((a, b) => {
    return new Date(a.created_at) - new Date(b.created_at);
  });

  container.innerHTML = `
    <div class="p-4 border-l-2 border-amber-400 space-y-6 ml-2">
      ${sortedHistory
        .map((item, index) => {
          const timeText = formatTime(item.created_at);
          const lat = Number(item.latitude).toFixed(5);
          const lng = Number(item.longitude).toFixed(5);

          return `
            <div class="relative">
              <span class="absolute -left-[21px] top-1 ${
                index === sortedHistory.length - 1 ? "bg-amber-400" : "bg-gray-600"
              } w-2.5 h-2.5 rounded-full"></span>
              <p class="text-xs text-gray-400">${timeText}</p>
              <p class="text-sm font-semibold">위치 기록</p>
              <p class="text-xs text-gray-500 mt-1">위도 ${lat}, 경도 ${lng}</p>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function showFeedLoading(message) {
  const container = $("feed-container");
  if (!container) return;

  container.innerHTML = `
    <div class="text-center py-12 text-gray-500 text-sm">
      ${escapeHTML(message)}
    </div>
  `;
}

function showFeedError(message) {
  const container = $("feed-container");
  if (!container) return;

  container.innerHTML = `
    <div class="text-center py-12 text-red-400 text-sm">
      <i class="fa-solid fa-triangle-exclamation mr-1"></i>
      ${escapeHTML(message)}
      <div class="text-gray-500 text-xs mt-2">
        백엔드 서버가 켜져 있는지, API 주소가 ${API_BASE_URL}인지 확인해주세요.
      </div>
    </div>
  `;
}



   // 8. 지도 히트맵 업데이트

function updateHeatmap(feedMessages = []) {
  if (!Array.isArray(feedMessages)) return;
  if (!map || !window.kakao || !window.kakao.maps) return;

  clearHeatmap();

  const groups = groupMessagesByLocation(feedMessages);

  groups.forEach((group) => {
    const position = new kakao.maps.LatLng(group.lat, group.lng);
    const overlay = new kakao.maps.CustomOverlay({
      position,
      xAnchor: 0.5,
      yAnchor: 0.5,
      clickable: true,
    });

    const badge = document.createElement("div");
    badge.className = "nowvibe-badge";
    badge.textContent = String(group.messages.length);

    badge.addEventListener("click", (event) => {
      event.stopPropagation();
      showMessagesAtLocation(group);
    });

    overlay.setContent(badge);
    overlay.setMap(map);
    messageOverlays.push(overlay);
      // 인기 메시지 말풍선 생성 시도
      const bubble = createPopularMessageBubbleOverlay(group);
      if (bubble) {
        messageBubbleOverlays.push(bubble);
      }
  });
}

function clearHeatmap() {
  heatCircles.forEach((circle) => circle.setMap(null));
  heatCircles = [];

  messageOverlays.forEach((overlay) => overlay.setMap(null));
  messageOverlays = [];

    // 인기 메시지 말풍선도 함께 제거
    messageBubbleOverlays.forEach((overlay) => overlay.setMap(null));
    messageBubbleOverlays = [];
}

function groupMessagesByLocation(feedMessages = []) {
  if (!Array.isArray(feedMessages)) return [];

  const groups = {};

  feedMessages.forEach((message) => {
    if (!Number.isFinite(message.latitude) || !Number.isFinite(message.longitude)) {
      return;
    }

    const latKey = message.latitude.toFixed(4);
    const lngKey = message.longitude.toFixed(4);
    const key = `${latKey}_${lngKey}`;

    if (!groups[key]) {
      groups[key] = {
        lat: Number(latKey),
        lng: Number(lngKey),
        messages: [],
      };
    }

    groups[key].messages.push(message);
  });

  return Object.values(groups);
}

function showMessagesAtLocation(group) {
  if (!group || !Array.isArray(group.messages)) return;

  selectedLocationGroup = group;
  renderFilterBar();
  renderFeed(group.messages);

  if (map && window.kakao && window.kakao.maps) {
    map.setCenter(new kakao.maps.LatLng(group.lat, group.lng));
  }
}

// 인기 메시지 관련 유틸 함수
function getTopLikedMessage(messages) {
  if (!Array.isArray(messages) || messages.length === 0) return null;

  return messages.reduce((best, msg) => {
    if (!best) return msg;

    if ((msg.likes || 0) > (best.likes || 0)) return msg;

    if ((msg.likes || 0) === (best.likes || 0)) {
      const a = new Date(msg.created_at || 0).getTime();
      const b = new Date(best.created_at || 0).getTime();
      return a > b ? msg : best;
    }

    return best;
  }, null);
}

function createPopularMessageBubbleOverlay(group) {
  if (!group || !Array.isArray(group.messages) || group.messages.length === 0) return null;
  if (!map || !window.kakao || !window.kakao.maps) return null;

  const top = getTopLikedMessage(group.messages);
  if (!top) return null;
  if ((top.likes || 0) < POPULAR_MESSAGE_LIKE_THRESHOLD) return null;

  const position = new kakao.maps.LatLng(group.lat, group.lng);

  const container = document.createElement('div');
  container.className = 'popular-message-bubble';
  container.style.cursor = 'pointer';

  const heartOpacity = getHeartOpacity(top.likes || 0);
  const heartScale = getHeartScale(top.likes || 0);

  container.innerHTML = `
    <div class="floating-heart" style="opacity: ${heartOpacity}; transform: scale(${heartScale});">❤</div>
    <div class="popular-message-text">${escapeHTML(truncateMessageText(top.text || ''))}</div>
    <div class="popular-message-like">❤️ ${top.likes || 0}</div>
  `;

  container.addEventListener('click', (ev) => {
    ev.stopPropagation();
    try {
      showMessagesAtLocation(group);
    } catch (e) {
      console.error('showMessagesAtLocation 호출 실패:', e);
    }
  });

  const overlay = new kakao.maps.CustomOverlay({
    position,
    content: container,
    xAnchor: 0.5,
    // yAnchor를 1.3으로 해서 배지보다 살짝 위에 표시
    yAnchor: 1.3,
    clickable: true,
  });

  overlay.setMap(map);

  return overlay;
}

function truncateMessageText(text, maxLength = 22) {
  if (!text) return '';
  const trimmed = text.trim();
  if (trimmed.length <= maxLength) return trimmed;
  return trimmed.slice(0, maxLength) + '...';
}

function getHeartOpacity(likes) {
  const n = Number(likes || 0);
  if (n <= 3) return 0.35; // 약한 opacity
  if (n < 10) return 0.6;
  if (n < 20) return 0.85;
  return 0.98; // 거의 선명
}

function getHeartScale(likes) {
  const n = Math.max(0, Number(likes || 0));
  const capped = Math.min(n, 20);
  // 0 -> 1.0, 20 -> 1.3
  const scale = 1 + (capped / 20) * 0.3;
  return Math.min(1.3, Math.max(1.0, scale));
}

function showAllMessages() {
  selectedLocationGroup = null;
  renderFilterBar();
  renderFeed(currentFeedMessages || []);
  updateHeatmap(currentFeedMessages || []);
}

  //  9. 메시지 생성

function bindFormSubmit() {
  const form = $("vibe-form");
  if (!form || form.dataset.submitBound === "true") return;

  form.addEventListener("submit", (event) => {
    console.trace("[FORM-SUBMIT] 폼 submit 이벤트 발생! 호출 스택:");
    handleSubmit(event);
  });

  form.dataset.submitBound = "true";
}

async function handleSubmit(event) {
  event.preventDefault();

  if (isSubmitting) return;
  isSubmitting = true;

  const input = $("vibe-input");
  const ttlSelect = $("ttl-select");
  const submitButton = document.querySelector('#vibe-form button[type="submit"]');

  if (submitButton) {
    submitButton.disabled = true;
    submitButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-1"></i> 올리는 중';
  }

  try {
    if (!input || !ttlSelect) return;

    const text = input.value.trim();
    const ttl = Number(ttlSelect.value);

    if (!text) {
      alert("메시지를 입력해주세요.");
      input.focus();
      return;
    }

    if (text.length > 100) {
      alert("메시지는 100자 이하로 입력해주세요.");
      input.focus();
      return;
    }

    const payload = {
      device_id: DEVICE_ID,
      text,
      latitude: userLat,
      longitude: userLng,
      location_name: "내 주변 캠퍼스",
      ttl,
      campus_id: CAMPUS_ID,
    };

    const requestBody = selectedFile
      ? buildMessageFormData(payload, selectedFile)
      : JSON.stringify(payload);

    await apiRequest("/messages", {
      method: "POST",
      body: requestBody,
    });

    input.value = "";
    clearFile();

    currentTab = "all";
    updateTabStyleOnly();
    renderFilterBar();
    await fetchMessages();

  } catch (error) {
    console.error("메시지 등록 실패:", error);
    alert(error.message || "메시지 등록에 실패했습니다.");
    
  } finally {
    isSubmitting = false;

    if (submitButton) {
      submitButton.disabled = false;
      submitButton.innerHTML = '<i class="fa-solid fa-paper-plane mr-1"></i> 올리기';
    }
  }
}

function buildMessageFormData(payload, file) {
  const formData = new FormData();

  Object.entries(payload).forEach(([key, value]) => {
    formData.append(key, value);
  });

  formData.append("image", file);

  return formData;
}

function updateTabStyleOnly() {
  const tabs = ["all", "current", "history"];

  tabs.forEach((tabName) => {
    const tabButton = $(`tab-${tabName}`);
    if (!tabButton) return;

    if (tabName === currentTab) {
      tabButton.className =
        "flex-1 py-4 text-center border-b-2 border-amber-400 text-amber-400 font-bold";
    } else {
      tabButton.className =
        "flex-1 py-4 text-center border-b-2 border-transparent text-gray-400 hover:text-gray-200";
    }
  });
}




  //   10. 좋아요 / 신고
    
async function toggleLike(messageId, isLiked) {
  try {
    if (isLiked) {
      const query = buildQuery({ device_id: DEVICE_ID });

      await apiRequest(`/messages/${messageId}/like?${query}`, {
        method: "DELETE",
        headers: {},
      });
    } else {
      await apiRequest(`/messages/${messageId}/like`, {
        method: "POST",
        body: JSON.stringify({
          device_id: DEVICE_ID,
        }),
      });
    }

    await loadTabData();
  } catch (error) {
    console.error("좋아요 처리 실패:", error);

    if (error.status === 409) {
      alert("이미 좋아요를 누른 메시지입니다.");
      await loadTabData();
      return;
    }

    alert(error.message || "좋아요 처리에 실패했습니다.");
  }
}

async function reportMessage(messageId) {
  const confirmed = confirm("이 메시지를 신고하시겠습니까?");
  if (!confirmed) return;

  try {
    await apiRequest(`/messages/${messageId}/report`, {
      method: "POST",
      body: JSON.stringify({
        device_id: DEVICE_ID,
      }),
    });

    alert("신고가 접수되었습니다.");
  } catch (error) {
    console.error("신고 실패:", error);

    if (error.status === 409) {
      alert("이미 신고한 메시지입니다.");
      return;
    }

    alert(error.message || "신고 처리에 실패했습니다.");
  }
}

  //   11. 상세 모달

async function openMessageModal(messageId) {
  const modal = $("detail-modal");
  const content = $("modal-content");

  if (!modal || !content) return;

  content.innerHTML = `
    <div class="text-center py-8 text-gray-500 text-sm">
      메시지를 불러오는 중입니다...
    </div>
  `;

  modal.classList.remove("hidden");

  try {
    const query = buildQuery({ device_id: DEVICE_ID });
    const data = await apiRequest(`/messages/${messageId}?${query}`);
    const message = normalizeMessages([data])[0];

    content.innerHTML = `
      <p class="text-base text-white font-medium my-2">
        "${escapeHTML(message.text)}"
      </p>

      ${
        message.image
          ? `<img src="${escapeAttribute(message.image)}" alt="첨부 이미지" class="w-full h-auto max-h-60 object-cover rounded-xl border border-gray-800">`
          : ""
      }

      <div class="flex justify-between items-center text-xs text-gray-400 pt-3 border-t border-gray-800">
        <span>
          <i class="fa-solid fa-map-pin mr-1"></i>
          위치: ${escapeHTML(message.location)}
        </span>
        <span>공유 시간: ${formatTime(message.created_at)}</span>
      </div>

      <div class="flex justify-between items-center text-xs text-gray-400 pt-2">
        <span>
          <i class="fa-regular fa-clock mr-1"></i>
          ${formatTTL(message)}
        </span>
        <span>
          <i class="fa-solid fa-heart mr-1 text-amber-400"></i>
          ${message.likes}
        </span>
      </div>
    `;
  } catch (error) {
    console.error("상세 조회 실패:", error);

    content.innerHTML = `
      <div class="text-center py-8 text-red-400 text-sm">
        ${escapeHTML(error.message || "상세 메시지를 불러오지 못했습니다.")}
      </div>
    `;
  }
}

function closeModal() {
  const modal = $("detail-modal");
  if (!modal) return;

  modal.classList.add("hidden");
}

  //   12. 이미지 선택 UI
  //   - 현재 백엔드는 image URL만 받는 구조입니다.
  //   - 실제 이미지 업로드는 별도 업로드 API가 필요합니다.

function triggerFileInput() {
  const fileInput = $("file-input");
  if (!fileInput) return;

  fileInput.click();
}

function handleFileChange() {
  const fileInput = $("file-input");
  const previewContainer = $("file-preview-container");
  const fileName = $("file-name");

  if (!fileInput || !previewContainer || !fileName) return;

  const file = fileInput.files && fileInput.files[0];

  if (!file) {
    clearFile();
    return;
  }

  selectedFile = file;

  if (selectedFilePreviewUrl) {
    URL.revokeObjectURL(selectedFilePreviewUrl);
  }

  selectedFilePreviewUrl = URL.createObjectURL(file);

  fileName.innerText = file.name;
  previewContainer.classList.remove("hidden");
}

function clearFile() {
  const fileInput = $("file-input");
  const previewContainer = $("file-preview-container");
  const fileName = $("file-name");

  selectedFile = null;

  if (selectedFilePreviewUrl) {
    URL.revokeObjectURL(selectedFilePreviewUrl);
    selectedFilePreviewUrl = null;
  }

  if (fileInput) {
    fileInput.value = "";
  }

  if (fileName) {
    fileName.innerText = "이미지 업로드됨";
  }

  if (previewContainer) {
    previewContainer.classList.add("hidden");
  }
}

   // 13. 표시 유틸리티

function formatTime(dateString) {
  if (!dateString) return "방금 전";

  const date = new Date(dateString);

  if (Number.isNaN(date.getTime())) {
    // "2026-06-02T14:30:00" 같은 문자열이면 일부만 표시
    if (typeof dateString === "string" && dateString.length >= 16) {
      return dateString.slice(11, 16);
    }

    return "방금 전";
  }

  return date.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTTL(message) {
  if (message.ttl === 999) {
    return "영구보존";
  }

  if (message.expires_at) {
    const expiresAt = new Date(message.expires_at);
    const now = new Date();

    if (!Number.isNaN(expiresAt.getTime())) {
      const diffMs = expiresAt.getTime() - now.getTime();
      const diffMinutes = Math.max(0, Math.ceil(diffMs / 1000 / 60));

      if (diffMinutes <= 0) return "만료 예정";
      if (diffMinutes < 60) return `남은시간: ${diffMinutes}분`;
      return `남은시간: ${Math.ceil(diffMinutes / 60)}시간`;
    }
  }

  return `남은시간: ${message.ttl}시간`;
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHTML(value).replaceAll("`", "&#096;");
}

/* =========================
   14. HTML inline onclick에서 접근 가능하도록 전역 등록
========================= */

window.switchTab = switchTab;
window.setSort = setSort;
window.fetchMessages = fetchMessages;
window.fetchNearbyMessages = fetchNearbyMessages;
window.fetchUserHistory = fetchUserHistory;
window.handleSubmit = handleSubmit;
window.toggleLike = toggleLike;
window.likeMessage = function likeMessage(event, id, isLiked = false) {
  if (event) event.stopPropagation();
  toggleLike(id, isLiked);
};
window.reportMessage = reportMessage;
window.openMessageModal = openMessageModal;
window.closeModal = closeModal;
window.triggerFileInput = triggerFileInput;
window.handleFileChange = handleFileChange;
window.clearFile = clearFile;
window.showAllMessages = showAllMessages;
