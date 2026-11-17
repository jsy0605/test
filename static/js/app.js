import {connectSimulator,stopSimulator} from './simulator-feed.js';
import { artworks, getArtwork, artImage, loadCatalog } from './data.js';
import { createSession, getSession, beginPreparation, registerVisitor, cancelPreparation, startSession, cancelSession, toggleDevAvailability, stopDevAvailability, injectDevPreparationReady, DEMO_MODE } from './services.js';
import { content } from './content.js';
import { serviceTerms } from './terms.js';
import { galleryMap } from './gallery-map.js';
import { courseSelection, selectedArtworks } from './course-selection.js';
import { watchCatalog } from './catalog-feed.js';
import { farewellPage, createAutoReturn } from './visit-handoff.js';
import { subscribeRobotAvailability } from './robot-availability.js';
import { subscribePreparation } from './robot-preparation.js';

const app = document.querySelector('#app');
const overlay = document.querySelector('#overlay');
let adminAuthenticated = false;
const icons = {
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  back: '<path d="m14 6-6 6 6 6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  robot: '<rect x="4" y="7" width="16" height="13" rx="5"/><path d="M12 3v4M9 16h6"/><circle cx="8" cy="12" r=".7"/><circle cx="16" cy="12" r=".7"/><path d="M1 11v5m22-5v5"/>',
  route: '<circle cx="6" cy="5" r="2"/><circle cx="18" cy="19" r="2"/><path d="M6 7v6a4 4 0 0 0 4 4h4a4 4 0 0 0 0-8h-2m3-6 3 3-3 3m3-3h-6"/>',
  walk: '<circle cx="14" cy="4" r="2"/><path d="m7 22 4-7 3 3v4M6 11l4-2 3-2 3 5h4m-7-5-2 8"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  pin: '<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  spark: '<path d="m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5Z"/>',
  volume: '<path d="M11 5 6 9H3v6h3l5 4V5Zm4 3a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  play: '<path d="m8 5 11 7-11 7V5Z"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
};
const icon = (name, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.spark}</svg>`;
const esc = text => String(text).replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
const state = { page: 'home', mode: null, selectedArtworkIds: [], session: null, stage: 'calling', visited: [], busy: false, termsAccepted: false, availabilityChecked: false, usageConfirmed: false, robotAvailability: {status:'waiting', available:null}, devReady:false, devValue:null, devBusy:false, devPreparationBusy:false };
let simulationEnabled=false;
let simulatedRuntime={};
let runtimeKey='';
let history = [];
let stopPreparation = null;
let preparation = {phase:'calling', message:'아티를 호출하고 있어요.', progress:0, connected:false};
let prepStep = 0;
let toastTimer;
let overlayTrigger;
const handedOffSessions = new Set();
const autoReturn = createAutoReturn({onReturn: returnHome});
function rememberPreparation(id) { try { if (id) sessionStorage.setItem('arti-preparation', id); else sessionStorage.removeItem('arti-preparation'); } catch {} }
function connectPreparation() {
  stopPreparation?.();
  const sessionId = state.session.id;
  stopPreparation = subscribePreparation(sessionId, snapshot => {
    if (state.session?.id !== sessionId) return;
    const next = snapshot.connected ? snapshot : {...preparation, connected:false};
    if (JSON.stringify(preparation) === JSON.stringify(next)) return;
    preparation = next;
    if (next.connected) {
      state.stage = next.phase;
      prepStep = ({calling:0,moving:1,arrived:2,registering:2,waiting_ready:3,ready:4})[next.phase] ?? prepStep;
      if (next.robot_id) state.session.robotId = next.robot_id;
    }
    if (state.page === 'session') render();
  });
}
const announce = text => { document.querySelector('#announcer').textContent = text; };
const toast = text => {
  const node = document.querySelector('#toast');
  clearTimeout(toastTimer); node.textContent = text; node.classList.add('visible');
  toastTimer = setTimeout(() => node.classList.remove('visible'), 3500);
};

function header() {
  return `<header class="header"><button class="brand" data-action="home" aria-label="Art I 처음 화면"><span>Art I</span><span class="brand-flower">✳</span><span class="brand-caption">YOUR PERSONAL<br>ART COMPANION</span></button>
    <div class="header-center">예술과 당신 사이, 아티</div>
    <div class="header-status"><span class="demo-label">키오스크 안내</span><span class="robot-status"><i></i> ${state.page === 'session' ? '아티 만남 준비 중' : state.session?.status === 'active' ? '아티와 함께 관람 중' : robotStatusLabel()}</span></div></header>`;
}

function footer() {
  return `<footer class="footer"><span><b>ART I GALLERY</b><span class="footer-divider">/</span> YOUR PERSONAL ART COMPANION</span><a href="/data" target="_blank" rel="noopener">관리자 페이지</a><div class="dev-controls" ${adminAuthenticated ? '' : 'hidden'}><button class="dev-toggle" data-action="dev-toggle" title="/is_available에 true/false를 1초마다 테스트 발행" ${!state.devReady || state.devBusy ? 'disabled' : ''}>dev1 <span class="dev-value">${state.devValue === null ? '대기' : String(state.devValue)}</span></button><button class="dev-toggle dev-preparation" data-action="dev-ready" title="오류 화면에 테스트용 관람 준비 완료 신호를 넣습니다" ${canUseDevPreparation() ? '' : 'disabled'}>dev2 <span>준비 완료 신호</span></button><button class="dev-stop" data-action="dev-stop" ${state.devValue === null ? 'hidden' : ''}>테스트 종료</button><span class="dev-publishing" ${state.devValue === null ? 'hidden' : ''}>1Hz 테스트 발행 중</span></div><span class="footer-note">${DEMO_MODE ? '로봇 준비 연동' : ''}</span></footer>`;
}

function sectionTop(eyebrow, title, description, back = 'mode') {
  return `<div class="page-top"><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${description}</p></div>`;
}


function home() {
  return `<section class="hero"><div class="hero-copy"><div class="eyebrow"><span class="tiny-line"></span> A NEW WAY TO EXPERIENCE ART</div><h1>당신의 취향을 따라,<br>예술을 만나는 시간<span class="orange-dot">.</span></h1><p class="hero-description">작품 앞의 작은 궁금증부터, 나만의 관람 여정까지.<br>당신만의 큐레이터 <b>아티</b>와 함께 걸어보세요.</p><div class="hero-proof"><span class="mini-robot">${icon('robot')}</span><span><b>당신의 속도로, 당신의 시선으로.</b><br>아래 메뉴를 눌러 이야기를 시작해 보세요.</span></div></div>
    <div class="hero-art hero-art--arti"><div class="art-orbit"></div><img class="hero-arti-image" src="/static/art/arti-welcome.png" alt="초록 베레모를 쓰고 깃발을 든 갤러리 큐레이터 아티" width="1334" height="1179" fetchpriority="high" decoding="async"><div class="hero-art-label"><span class="live-dot"></span> YOUR ART COMPANION<span>갤러리 큐레이터 아티</span></div></div></section>
    <section class="home-menu" aria-label="키오스크 주 메뉴"><button class="home-menu-card" data-action="exhibition"><div class="menu-card-top"><span class="menu-icon">${icon('image')}</span><span class="menu-number">01</span></div><div class="menu-card-bottom"><div><h2>갤러리 소개</h2><p>공간과 전시의 이야기를 만나보세요</p></div>${icon('arrow')}</div></button><button class="home-menu-card featured-menu" data-action="begin-visit" ${hasAvailableRobot() ? '' : 'disabled'}><div class="menu-card-top"><span class="menu-icon">${icon('robot')}</span><span class="menu-number">02</span></div><div class="menu-card-bottom"><div><h2>Art I 호출하기</h2><p>나만의 큐레이터와 관람을 시작하세요</p></div><span class="menu-round-arrow">${icon('arrow')}</span></div></button></section><p class="availability-message" role="status" ${availabilityNotice() ? '' : 'hidden'}>${esc(availabilityNotice())}</p><div class="home-bottom"><span class="live-dot"></span> 잠깐의 호기심이, 특별한 관람이 되는 곳.<span>EXPLORE AT YOUR OWN PACE</span></div>`;
}

function termsPage() {
  return `${sectionTop('BEFORE YOUR JOURNEY', '관람 전, 이용약관을 확인해 주세요', '안내 내용을 읽고 필수 항목에 동의하면 관람 방법을 선택할 수 있어요.', 'home')}
    <ol class="terms-progress" aria-label="관람 준비 단계">
      <li aria-current="step"><span>01</span> 이용약관 동의</li>
      <li><span>02</span> 관람 방법 선택</li>
      <li><span>03</span> 아티 만나기</li>
    </ol>
    <div class="terms-layout">
      <section class="terms-document" aria-labelledby="terms-title">
        <div class="terms-document-heading"><h2 id="terms-title">${esc(serviceTerms.title)}</h2><span class="small-tag">필수</span></div>
        <div class="terms-body" tabindex="0" role="region" aria-label="이용약관 본문">
          <p class="terms-draft">${esc(serviceTerms.note)}</p>
          ${serviceTerms.sections.map(section => `<section><h3>${esc(section.title)}</h3>${section.paragraphs.map(text => `<p>${esc(text)}</p>`).join('')}</section>`).join('')}
        </div>
        <label class="terms-consent" for="terms-consent">
          <input id="terms-consent" type="checkbox" ${state.termsAccepted ? 'checked' : ''} required>
          <span><b><span class="terms-required">[필수]</span> 서비스 이용약관에 동의합니다.</b><small>위 안내 내용을 확인했어요.</small></span>
        </label>
      </section>
      <aside class="terms-next">
        <span class="terms-robot">${icon('robot')}</span>
        <span class="eyebrow">A LITTLE CHECK, THEN ART</span>
        <h2>즐거운 관람을 위한<br>작은 약속이에요.</h2>
        <p>필수 약관에 동의한 후<br>나에게 맞는 관람 방법을 골라보세요.</p>
        <div class="terms-next-hint">${icon('route')} 코스 주행 <span>또는</span> ${icon('walk')} 사용자 추종</div>
        <button class="button primary full" data-action="accept-terms" ${state.termsAccepted ? '' : 'disabled'}>동의하고 다음으로 ${icon('arrow')}</button>
        <button class="terms-decline" data-action="home">동의하지 않고 돌아가기</button>
      </aside>
    </div>`;
}

function modePage() {
  return `${sectionTop('YOUR OWN WAY', '오늘의 관람 방법을 골라주세요', '앞장서는 아티, 혹은 당신을 따라 걷는 아티. 어떤 만남도 좋아요.', 'home')}<div class="mode-grid"><button class="mode-card" data-action="choose-mode" data-mode="course"><div class="mode-illustration course-illustration"><span class="illustration-art art-one"></span><span class="illustration-art art-two"></span><span class="dotted-path"></span><span class="illustration-person">${icon('walk')}</span><span class="illustration-robot">${icon('robot')}</span><span class="illustration-label">아티가 안내해요</span></div><div class="mode-card-content"><span class="eyebrow">GUIDED COURSE</span><h2>코스 주행</h2><p>보고 싶은 작품을 체크해 주세요.<br>아티가 앞장서 작품을 차례로 안내해요.</p><div class="mode-card-bottom"><span>${icon('clock')} 약 15분</span><span class="round-arrow">${icon('arrow')}</span></div></div></button><button class="mode-card" data-action="choose-mode" data-mode="free"><div class="mode-illustration free-illustration"><span class="illustration-art art-one"></span><span class="illustration-art art-two"></span><span class="dotted-path"></span><span class="illustration-person">${icon('walk')}</span><span class="illustration-robot">${icon('robot')}</span><span class="illustration-label">당신이 앞장서요</span></div><div class="mode-card-content"><span class="eyebrow">FREE EXPLORATION</span><h2>사용자 추종</h2><p>마음이 이끄는 대로 자유롭게 걸어보세요.<br>아티가 따라가며 작품 이야기를 들려줘요.</p><div class="mode-card-bottom"><span>${icon('spark')} 자유 관람</span><span class="round-arrow">${icon('arrow')}</span></div></div></button></div><p class="center-note">${icon('robot')} 관람 시작 전, 아티가 함께할 관람객 한 분을 확인해요.</p>`;
}

function selectedIds() {
  return state.mode === 'free' ? artworks.map(art => art.id)
    : selectedArtworks(artworks, state.selectedArtworkIds).map(art => art.id);
}

function coursePage() {
  const ids = selectedIds();
  return `<div class="course-workspace"><div class="course-intro">${sectionTop('CHOOSE YOUR ARTWORKS', '관람할 작품을<br>선택해 주세요', '여러 작품을 선택할 수 있어요.')}<p class="catalog-status" data-catalog-status role="status">작품 정보는 DB에서 자동 갱신돼요.</p></div>
    ${courseSelection(artworks, state.selectedArtworkIds)}
    <section class="course-map-panel" aria-labelledby="course-map-heading"><div class="preview-heading"><span class="eyebrow">GALLERY MAP</span><h2 id="course-map-heading">작품 위치</h2></div>${galleryMap(ids)}</section>
    <div class="course-selection-next"><span class="selection-count">선택한 작품 <b>${ids.length}개</b></span><button class="button primary" data-action="call" ${!ids.length || state.busy ? 'disabled' : ''}>아티 만나기 ${icon('arrow')}</button></div></div>`;
}

function freePage() {
  return `${sectionTop('FOLLOW YOUR CURIOSITY', '당신의 발걸음에 함께할게요', '보고 싶은 작품을 자유롭게 만나세요. 아티가 곁에서 이야기를 더해요.')}<div class="free-layout"><div class="free-intro"><div class="free-big-icon">${icon('walk')}<span class="dashed-connector"></span>${icon('robot')}</div><h2>정해진 길 없이,<br>마음에 드는 작품 앞에서.</h2><p>아티 앞에서 관람객 등록을 마친 뒤 천천히 걸어주세요.<br>작품 앞에서 잠시 머무르면 해설이 시작돼요.</p><ul class="instruction-list"><li><span>01</span><div><b>아티에게 나를 알려주세요</b><p>키오스크 스캔 지점에서 한 분만 아티 앞에 서 주세요.</p></div></li><li><span>02</span><div><b>작품 앞에서 잠시 멈춰보세요</b><p>관람 구역에서 머무르면 작품을 소개해요.</p></div></li><li><span>03</span><div><b>다시 걸으면, 함께 걸어요</b><p>작품을 떠나면 설명을 멈추고 따라가요.</p></div></li></ul></div><aside class="course-preview"><div class="preview-heading"><span class="eyebrow">MEET YOUR ARTI</span><h2>아티와 만날 장소</h2></div>${galleryMap([])}<div class="meeting-caption">${icon('pin')} 키오스크 앞 · 관람객 스캔 지점</div><div class="soft-notice">${icon('volume')} 주변 관람객을 배려하며<br>아티와 함께 천천히 이동해 주세요.</div><button class="button primary full" data-action="call" ${state.busy ? 'disabled' : ''}>자유 관람 아티 만나기 ${icon('arrow')}</button><p class="preview-note">아티가 키오스크 앞으로 도착하면 관람객을 등록해요.</p></aside></div>`;
}



function sessionPage() {
  const s = state.session;
  const phase = state.stage;
  const titles = {calling:'아티를 호출하고 있어요', moving:'아티가 당신을 만나러 가고 있어요', arrived:'아티가 도착했어요!', registering:'함께할 관람객을 확인하고 있어요', waiting_ready:'관람 준비를 마무리하고 있어요', ready:'반가워요, 이제 함께 걸어볼까요?', error:'로봇 상태를 확인해 주세요', cancelling:'호출을 취소하고 있어요', cancelled:'호출이 취소됐어요'};
  const moving = ['calling','moving'].includes(phase);
  const robotImage = moving ? {src:'/static/art/arti-on-the-way.png',alt:'만나러 오는 아티',width:1024,height:1024} : {src:'/static/art/arti-arrived.png',alt:'도착한 아티',width:1024,height:1024};
  const connected = preparation.connected;
  const message = connected ? preparation.message : '진행 상태 연결을 확인하고 있어요. 연결이 복구되면 이어서 표시해요.';
  const controls = phase === 'arrived'
    ? `<button class="button primary full" data-action="register" ${connected ? '' : 'disabled'}>아티 앞에 섰어요 · 등록 시작 ${icon('arrow')}</button>`
    : phase === 'ready' ? `<button class="button primary full" data-action="start-tour" ${connected ? '' : 'disabled'}>관람 시작하기 ${icon('arrow')}</button>`
    : phase === 'error' && adminAuthenticated ? `<button class="button secondary full" data-action="dev-ready" ${canUseDevPreparation() ? '' : 'disabled'}>dev2 · 준비 완료 신호 넣기 ${icon('arrow')}</button>` : ['error','cancelled'].includes(phase) ? '' : `<div class="waiting-label"><span class="spinner"></span>${['moving','registering'].includes(phase) && connected ? `${Math.round(preparation.progress * 100)}%` : '응답 대기 중…'}</div>`;
  return `<div class="session-top"><div class="eyebrow">LET’S MEET</div><h1>${titles[phase] || titles.calling}</h1><p role="status">${esc(message)}</p></div><div class="session-layout"><div class="robot-panel session-robot-panel"><img class="session-robot-image" src="${robotImage.src}" alt="${robotImage.alt}" width="${robotImage.width}" height="${robotImage.height}" decoding="async"><div class="robot-name">${esc(s.robotId)}</div><span class="robot-panel-caption">YOUR PERSONAL ART COMPANION</span></div><div class="session-details"><ol class="session-steps">${['아티 호출','만남 장소 도착','관람객 등록','관람 준비 완료'].map((name,i) => `<li class="${i < prepStep ? 'done' : i === prepStep ? 'current' : ''}"><span>${i < prepStep ? icon('check') : String(i+1).padStart(2,'0')}</span><div><b>${name}</b>${i === prepStep ? '<small>로봇 응답 확인 중</small>' : ''}</div></li>`).join('')}</ol><div class="session-meeting">${icon('pin')}<div><b>키오스크 앞 · 관람객 스캔 지점</b><p>${s.mode === 'free' ? '자유 관람' : '선택한 작품 관람'} · ${s.artworkIds.length}개 작품</p></div></div>${controls}<p class="preview-note">${preparation.dev_mode ? 'dev2 화면 테스트 · 실제 로봇의 이동·등록 신호가 아닙니다.' : phase === 'error' && adminAuthenticated ? 'dev2로 준비 완료 신호를 넣어 다음 관람 화면을 테스트할 수 있어요.' : '아티 정면에 한 분만 서서 기다려 주세요.'}</p><button class="cancel-link" data-action="cancel-session">호출 취소하기</button></div></div>`;
}

function collectionSection() {
  return `<section class="collection-section" aria-labelledby="collection-heading"><div class="collection-heading"><div><span class="eyebrow">THE COLLECTION · 2026</span><h2 id="collection-heading">작품으로 만나는, 하나의 전시</h2></div><p>작품을 눌러 아티의 이야기를 만나보세요.</p></div><div class="collection-grid">${artworks.map(art => `<button class="collection-card" data-action="view-art" data-id="${esc(art.id)}" aria-label="${esc(art.title)} 작품 상세 보기"><div class="collection-image"><img src="${esc(artImage(art))}" alt="${esc(art.image_alt || art.title)}" width="1536" height="1024" loading="lazy"><span class="collection-code">${esc(art.artwork_code)}</span></div><div class="collection-copy"><span class="small-tag">${esc(art.theme)}</span><h3>${esc(art.title)}</h3><p class="collection-english" lang="en">${esc(art.title_en)}</p><p class="collection-artist">${esc(art.artist)}</p><span class="collection-link">작품 이야기 ${icon('arrow')}</span></div></button>`).join('')}</div></section>`;
}

function showArtwork(id) {
  const art = getArtwork(id);
  if (!art) return;
  showDialog(`<article class="artwork-detail"><div class="artwork-detail-image"><img src="${esc(artImage(art))}" alt="${esc(art.image_alt || art.title)}" width="1536" height="1024"></div><div class="artwork-detail-copy"><div class="artwork-detail-overline"><span class="eyebrow">${esc(art.artwork_code)}</span><span class="small-tag">${esc(art.theme)}</span></div><h2>${esc(art.title)}</h2><p class="artwork-title-en" lang="en">${esc(art.title_en)}</p><p class="artwork-artist">${esc(art.artist)} <span lang="en">${esc(art.artist_name_en)}</span></p><div class="artwork-description">${art.description.split(/\n\s*\n/).map(paragraph => `<p>${esc(paragraph)}</p>`).join('')}</div></div></article>`, `${esc(art.title)} 작품 상세`);
}

function mediaPage(kind) {
  const item = content[kind];
  const media = item.media;
  const player = media.src
    ? media.type === 'image'
      ? `<img class="content-image" src="${esc(media.src)}" alt="${esc(media.alt || item.title)}" width="${media.width}" height="${media.height}" decoding="async">`
      : media.type === 'audio'
      ? `<div class="audio-player"><div class="audio-symbol">${icon('volume')}</div><audio controls preload="metadata" src="${esc(media.src)}">이 브라우저에서는 오디오를 재생할 수 없습니다.</audio></div>`
      : `<video class="content-video" controls playsinline preload="metadata" src="${esc(media.src)}" ${media.poster ? `poster="${esc(media.poster)}"` : ''}>이 브라우저에서는 동영상을 재생할 수 없습니다.</video>`
    : `<div class="media-placeholder ${kind === 'usage' ? 'usage-placeholder' : ''}">${media.poster ? `<img src="${esc(media.poster)}" alt="갤러리 안내 콘텐츠 표지">` : ''}<div class="placeholder-overlay"><span class="placeholder-icon">${icon(kind === 'usage' ? 'robot' : 'play')}</span><span class="eyebrow">${kind === 'usage' ? 'HOW TO ENJOY ART I' : 'THE GALLERY STORY'}</span><h2>${kind === 'usage' ? '당신만의 큐레이터, Art I' : '예술과 당신이 만나는 공간'}</h2><span class="content-pending">안내 콘텐츠 준비 중</span></div></div>`;
  return `${sectionTop(item.eyebrow, item.title, item.description, 'home')}<section class="media-layout"><div class="media-screen">${player}<p class="media-error" role="status" hidden>안내 콘텐츠를 불러오지 못했어요. 잠시 후 다시 이용해 주세요.</p><div class="media-caption"><span>${icon(media.type === 'image' ? 'image' : media.type === 'audio' ? 'volume' : 'play')} ${media.type === 'image' ? (kind === 'usage' ? 'SERVICE NOTICE' : 'GALLERY INTRODUCTION') : media.type === 'audio' ? 'AUDIO GUIDE' : 'GALLERY FILM'}</span><span>${media.type === 'image' ? (kind === 'usage' ? '안전한 관람을 위해 안내 내용을 확인해 주세요' : '갤러리와 전시의 이야기를 만나보세요') : media.src ? '재생 버튼을 눌러 안내를 시작하세요' : '곧 새로운 이야기로 만나요'}</span></div></div><aside class="media-description"><span class="eyebrow">${kind === 'usage' ? 'THREE LITTLE STEPS' : 'A MOMENT FOR ART'}</span><h2>${item.caption}</h2><p>${item.text}</p>${kind === 'usage' ? `<ol class="instruction-list"><li><span>01</span><div><b>관람 방법 고르기</b><p>코스 주행 또는 사용자 추종을 선택해요.</p></div></li><li><span>02</span><div><b>아티 만나고 등록하기</b><p>한 분만 아티 정면에 서 주세요.</p></div></li><li><span>03</span><div><b>작품 이야기 만나기</b><p>코스 주행은 아티를 따라가고,<br>사용자 추종은 내가 먼저 걸어요.</p></div></li></ol>` : `<div class="gallery-quote"><span>“</span><p>작품을 이해하는 정답보다,<br>당신이 느끼는 순간을 위해.</p><small>ART I GALLERY</small></div>`}${kind === 'usage' ? `<button class="button primary full" data-action="continue-usage">사용방법을 확인했어요 · 다음으로 ${icon('arrow')}</button>` : ''}</aside></section>${kind === 'exhibition' ? collectionSection() : ''}`;
}

const pages = { home, terms: termsPage, mode: modePage, course: coursePage, free: freePage, exhibition: () => mediaPage('exhibition'), usage: () => mediaPage('usage'), session: sessionPage, farewell: farewellPage };
function render({ focus = false, scroll = false } = {}) {
  const farewell = state.page === 'farewell';
  app.innerHTML = farewell
    ? `<main id="main" class="main page-farewell" tabindex="-1">${farewellPage()}</main>`
    : `${simulationEnabled ? `<aside style="background:#e4eedb;padding:12px 24px;color:#29432e">테스트 모드 · 실제 로봇 연결 없음 <a href="/remote" target="_blank" rel="noopener">신호 리모컨 열기 ↗</a>${simulatedRuntime.message ? `<strong style="display:block;margin-top:8px">${esc(simulatedRuntime.message)}</strong>` : ''}</aside>` : ''}${header()}<main id="main" class="main page-${state.page}" tabindex="-1">${pages[state.page]()}</main>${footer()}<button class="global-back" data-action="back" ${!history.length && state.page === 'home' ? 'disabled' : ''} aria-label="이전 화면으로 돌아가기">${icon('back')} 뒤로가기</button>`;
  if (farewell) autoReturn.start(state.session.id);
  else autoReturn.cancel();
  app.querySelectorAll('video, audio, .content-image').forEach(media => media.addEventListener('error', () => { const error=app.querySelector('.media-error'); if(error) error.hidden=false; }));
  if (scroll) window.scrollTo({ top:0, behavior:'instant' });
  if (focus && !overlay.firstElementChild) { document.querySelector('#main').focus({preventScroll:true}); announce(document.querySelector('h1')?.textContent || ''); }
}

function navigate(page) {
  if (['terms', 'mode', 'course', 'free'].includes(page)) {
    if (!state.availabilityChecked) page = 'home';
    else if (!state.usageConfirmed) page = 'usage';
  }
  if (['mode', 'course', 'free'].includes(page) && !state.termsAccepted) page = 'terms';
  if (state.page === page) return;
  if (state.session && state.page === 'session') {
    confirmDialog('관람을 종료할까요?', '다른 화면으로 이동하면 진행 중인 체험이 종료돼요.', async () => { await cancelCurrent(); if (page === 'home') { history=[]; resetEntry(); } else history.push(state.mode === 'course' ? 'course' : 'free'); state.page=page; render({focus:true,scroll:true}); });
    return;
  }
  if (page === 'home') { history=[]; state.session=null; resetEntry(); } else history.push(state.page); state.page = page; render({focus:true, scroll:true});
}

function resetEntry() {
  state.selectedArtworkIds = [];
  state.termsAccepted = false;
  state.availabilityChecked = false;
  state.usageConfirmed = false;
}

function hasAvailableRobot() {
  return state.robotAvailability.status === 'available' && state.robotAvailability.available === true;
}

function robotStatusLabel() {
  if (hasAvailableRobot()) return '아티를 호출할 수 있어요';
  if (state.robotAvailability.status === 'unavailable') return '이용 가능한 아티가 없어요';
  return '아티 상태 수신 대기';
}

function availabilityNotice() {
  if (hasAvailableRobot()) return '';
  if (state.robotAvailability.status === 'unavailable') return '사용 가능한 로봇이 없습니다. 잠시 후 다시 이용해 주세요.';
  if (['stale', 'disconnected'].includes(state.robotAvailability.status)) return '로봇 상태 연결이 끊겼어요. 연결을 확인하고 있습니다.';
  return '로봇 상태를 수신하고 있습니다. 잠시 기다려 주세요.';
}

function receiveRobotAvailability(snapshot) {
  const changed = snapshot.status !== state.robotAvailability.status || snapshot.available !== state.robotAvailability.available;
  state.robotAvailability = snapshot;
  if (snapshot.devReady !== undefined) state.devReady = snapshot.devReady;
  else if (snapshot.status === 'disconnected') state.devReady = false;
  if (snapshot.devValue !== undefined) state.devValue = snapshot.devValue;
  syncDeveloperControls();
  const status = document.querySelector('.robot-status');
  if (status && !state.session) { status.innerHTML = '<i></i> ' + robotStatusLabel(); status.classList.toggle('is-unavailable', !hasAvailableRobot()); }
  const button = document.querySelector('[data-action="begin-visit"]');
  if (button) button.disabled = !hasAvailableRobot();
  const notice = document.querySelector('.availability-message');
  if (notice) { notice.textContent = availabilityNotice(); notice.hidden = hasAvailableRobot(); }
  if (changed && state.page === 'home') announce(hasAvailableRobot() ? '아티를 호출할 수 있어요.' : availabilityNotice());
}

function canUseDevPreparation() {
  return adminAuthenticated && state.page === 'session' && state.session?.status === 'calling'
    && !state.devPreparationBusy && (state.stage === 'error' || !preparation.connected);
}

async function completeDeveloperPreparation() {
  if (!canUseDevPreparation()) return;
  state.devPreparationBusy = true;
  render();
  const sessionId = state.session.id;
  try {
    const snapshot = await injectDevPreparationReady(state.session);
    if (state.session?.id !== sessionId) return;
    preparation = {...snapshot, connected:true};
    state.stage = snapshot.phase;
    state.session.robotId = snapshot.robot_id;
    prepStep = 4;
    connectPreparation();
    announce('dev2 준비 완료 신호를 넣었어요. 관람 시작하기를 눌러 주세요.');
  } catch (error) {
    toast(error.message || '테스트 신호를 넣지 못했어요. 다시 시도해 주세요.');
  } finally {
    state.devPreparationBusy = false;
    render();
  }
}

function syncDeveloperControls() {
  document.querySelectorAll('[data-action="dev-ready"]').forEach(button => { button.disabled = !canUseDevPreparation(); });
  const button = document.querySelector('[data-action="dev-toggle"]');
  if (!button) return;
  button.disabled = !state.devReady || state.devBusy;
  button.classList.toggle('is-publishing', state.devValue !== null);
  button.querySelector('.dev-value').textContent = state.devValue === null ? '대기' : String(state.devValue);
  const stop = document.querySelector('[data-action="dev-stop"]');
  stop.hidden = state.devValue === null;
  stop.disabled = state.devBusy;
  document.querySelector('.dev-publishing').hidden = state.devValue === null;
}

async function changeDeveloperAvailability(action) {
  if (state.devBusy) return;
  state.devBusy = true;
  syncDeveloperControls();
  try {
    const result = action === 'stop' ? await stopDevAvailability() : await toggleDevAvailability();
    state.devReady = result.dev_ready;
    state.devValue = result.dev_value;
    announce(action === 'stop' ? '토픽 테스트 발행을 종료했어요.' : `is_available ${result.dev_value} 테스트 발행을 시작했어요.`);
  } catch (error) {
    toast(error.message || '테스트 값을 변경하지 못했어요. 다시 시도해 주세요.');
  } finally {
    state.devBusy = false;
    syncDeveloperControls();
  }
}

function beginVisit() {
  if (!hasAvailableRobot()) return;
  state.availabilityChecked = true;
  state.usageConfirmed = false;
  state.termsAccepted = false;
  navigate('usage');
}

function goBack() {
  if (overlay.firstElementChild) return closeDialog();
  if (state.page === 'farewell') return returnHome();
  if (state.page === 'session') {
    confirmDialog('이전 화면으로 돌아갈까요?', '진행 중인 호출 또는 관람 체험이 종료돼요.', async () => { await cancelCurrent(); state.page=history.pop() || 'mode'; render({focus:true,scroll:true}); });
    return;
  }
  state.page=history.pop() || 'home';
  if (state.page === 'home') resetEntry();
  render({focus:true,scroll:true});
}

function showDialog(content, label) {
  overlayTrigger = document.activeElement;
  overlay.innerHTML = `<div class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-label="${label}" tabindex="-1"><button class="modal-close" data-action="close-modal" aria-label="닫기">${icon('close')}</button>${content}<button class="modal-back" data-action="close-modal">${icon('back')} 뒤로가기</button></section></div>`;
  document.body.classList.add('modal-open');
  overlay.querySelector('.modal').focus();
}
function closeDialog() {
  overlay.innerHTML = ''; document.body.classList.remove('modal-open');
  if (overlayTrigger?.isConnected) overlayTrigger.focus();
  dialogAction = null;
}
let dialogAction = null;
function confirmDialog(title, description, action) {
  showDialog(`<div class="confirm-content"><span class="confirm-icon">${icon('robot')}</span><h2>${title}</h2><p>${description}</p><div class="dialog-actions"><button class="button secondary" data-action="close-modal">계속 관람하기</button><button class="button primary" data-action="confirm">종료하기</button></div></div>`, title);
  dialogAction = action;
}
function help() {
  return beginVisit();
}

async function callRobot() {
  if (!state.availabilityChecked || !state.usageConfirmed) { navigate('home'); return; }
  if (!state.termsAccepted) { navigate('terms'); return; }
  if (state.busy) return;
  if (!selectedIds().length) { toast('관람할 작품을 하나 이상 선택해 주세요.'); return; }
  state.busy = true; render();
  try {
    if (!hasAvailableRobot()) { navigate('home'); return; }
    state.session = await createSession({ mode:state.mode, artworkIds:selectedIds(), courseId:null });
    state.stage='calling'; prepStep=0; preparation={phase:'calling',message:'아티를 호출하고 있어요.',progress:0,connected:false}; state.visited=[];
    rememberPreparation(state.session.id);
    history.push(state.page); state.page='session'; render({focus:true,scroll:true});
    await beginPreparation(state.session);
    connectPreparation();
  } catch(error) {
    if (state.page === 'session') { state.stage='error'; preparation={...preparation,connected:true,message:error.message}; }
    toast(error.message || '호출하지 못했어요. 다시 시도해 주세요.');
  }
  finally { state.busy=false; render(); }
}
function showFarewell() {
  stopPreparation?.(); stopPreparation = null;
  rememberPreparation(null);
  handedOffSessions.add(state.session.id);
  history = [];
  state.page = 'farewell';
  render({focus:true, scroll:true});
}

function returnHome() {
  autoReturn.cancel();
  stopPreparation?.(); stopPreparation = null;
  rememberPreparation(null);
  if (overlay.firstElementChild) closeDialog();
  simulatedRuntime = {}; runtimeKey = ''; history = [];
  state.session = null; state.mode = null; state.visited = [];
  state.stage = 'calling'; prepStep = 0;
  preparation = {phase:'calling', message:'아티를 호출하고 있어요.', progress:0, connected:false};
  resetEntry(); state.page = 'home';
  // 화면을 반환할 뿐, 이미 시작한 관람을 취소하거나 완료로 저장하지 않습니다.
  render({focus:true, scroll:true});
}

async function cancelCurrent() {
  await cancelPreparation(state.session);
  await cancelSession(state.session, state.visited);
  stopPreparation?.(); rememberPreparation(null); state.session=null;
}
function watchSimulatedSession(){
  connectSimulator(null,data=>{
    if(data.disconnected){
      runtimeKey='';simulatedRuntime={message:'모의 상태 수신이 중단됐어요. 리모컨에서 수신 ON을 보내 주세요.'};render();return;
    }
    if(!data.runtime?.phase || !data.session || handedOffSessions.has(data.session.id))return;
    const key=JSON.stringify([data.runtime,data.preparation]);if(key===runtimeKey)return;runtimeKey=key;
    if(data.preparation?.phase==='cancelled' && data.runtime.preparation_phase!=='cancelled')return;
    stopPreparation?.();stopPreparation=null;
    simulatedRuntime=data.runtime;state.session=data.session;state.visited=data.session.visitedIds;
    state.mode=data.session.mode;state.selectedArtworkIds=[...data.session.artworkIds];
    if(data.runtime.preparation_phase){
      preparation={...data.preparation,connected:true};state.stage=preparation.phase;
      prepStep=({calling:0,moving:1,arrived:2,registering:2,waiting_ready:3,ready:4})[state.stage]??0;
      state.page='session';rememberPreparation(state.session.id);
    }else{
      showFarewell();
      return;
    }
    render();
  });
}

let handlingClick = false;
document.addEventListener('click', async event => {
  const target = event.target.closest('[data-action]');
  if (!target || target.disabled || handlingClick) return;
  handlingClick = true;
  try {
  const action = target.dataset.action;
  if (action === 'view-art') return showArtwork(target.dataset.id);
  if (action === 'dev-toggle') return await changeDeveloperAvailability('toggle');
  if (action === 'dev-stop') return await changeDeveloperAvailability('stop');
  if (action === 'dev-ready') return await completeDeveloperPreparation();
  if (['home','mode','exhibition','usage'].includes(action)) return navigate(action);
  if (action === 'begin-visit') return await beginVisit();
  if (action === 'continue-usage') {
    if (!state.availabilityChecked) return navigate('home');
    state.usageConfirmed = true;
    return navigate('terms');
  }
  if (action === 'accept-terms') {
    if (!state.termsAccepted) return;
    return navigate('mode');
  }
  if (action === 'back') return goBack();
  if (action === 'help') return await help();
  if (action === 'close-modal') return closeDialog();
  if (action === 'confirm') { const fn=dialogAction; closeDialog(); await fn?.(); return; }
  if (action === 'choose-mode') { state.mode=target.dataset.mode; navigate(state.mode === 'course' ? 'course' : 'free'); }
  if (action === 'select-all-artworks') {
    state.selectedArtworkIds = artworks.map(art => art.id);
    render(); document.querySelector('[data-action="clear-artworks"]').focus({preventScroll:true});
  }
  if (action === 'clear-artworks') {
    state.selectedArtworkIds = [];
    render(); document.querySelector('[data-action="select-all-artworks"]').focus({preventScroll:true});
  }
  if (action === 'call') await callRobot();
  if (action === 'register') {
    if (state.stage !== 'arrived') return;
    if (!preparation.connected) return;
    await registerVisitor(state.session);
  }
  if (action === 'start-tour') {
    if (state.stage !== 'ready' || !preparation.connected) return;
    state.session = await startSession(state.session);
    showFarewell();
  }
  if (action === 'cancel-session') confirmDialog('아티 호출을 취소할까요?', '호출을 취소하면 관람 방법 선택으로 돌아가요.', async () => { await cancelCurrent(); history=['home','usage','terms']; state.page='mode'; render({focus:true,scroll:true}); });
  if (action === 'reset') return returnHome();
  } catch (error) {
    toast(error.message || '저장하지 못했어요. 다시 시도해 주세요.');
  } finally {
    handlingClick = false;
  }
});

document.addEventListener('change', event => {
  if (event.target.matches('[data-artwork-choice]')) {
    const id = event.target.dataset.artworkChoice;
    state.selectedArtworkIds = event.target.checked
      ? [...new Set([...state.selectedArtworkIds, id])]
      : state.selectedArtworkIds.filter(item => item !== id);
    render(); document.querySelector(`[data-artwork-choice="${CSS.escape(id)}"]`).focus({preventScroll:true});
    return;
  }
  if (event.target.id !== 'terms-consent') return;
  state.termsAccepted = event.target.checked;
  const nextButton = document.querySelector('[data-action="accept-terms"]');
  if (nextButton) nextButton.disabled = !state.termsAccepted;
  announce(state.termsAccepted ? '이용약관에 동의했어요. 다음 단계로 진행할 수 있어요.' : '필수 약관에 동의해야 다음 단계로 진행할 수 있어요.');
});

document.addEventListener('visibilitychange', () => { if (!document.hidden && state.page === 'farewell') autoReturn.resume(); });

document.addEventListener('keydown', event => {
  const modal=overlay.querySelector('.modal');
  if (!modal) return;
  if (event.key === 'Escape') closeDialog();
  if (event.key === 'Tab') {
    const list=[...modal.querySelectorAll('button:not([disabled]), a[href], input, [tabindex="0"]')];
    const first=list[0],last=list.at(-1);
    if (event.shiftKey && (document.activeElement===first || document.activeElement===modal)) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && (document.activeElement===last || document.activeElement===modal)) { event.preventDefault(); first?.focus(); }
  }
});
function connectCatalog() {
  stopCatalog?.();
  stopCatalog = watchCatalog({
    refresh: options => ['course', 'free', 'exhibition'].includes(state.page) ? loadCatalog(options) : false,
    onUpdate: changed => {
      if (changed && ['course', 'free', 'exhibition', 'home'].includes(state.page) && !state.busy) {
        const focusId = document.activeElement?.id;
        render();
        if (focusId) document.getElementById(focusId)?.focus({preventScroll:true});
      }
      const status = document.querySelector('[data-catalog-status]');
      if (status) status.textContent = '작품 정보는 DB에서 자동 갱신돼요.';
    },
    onError: () => {
      const status = document.querySelector('[data-catalog-status]');
      if (status) status.textContent = 'DB 연결을 확인하고 있어요. 마지막 조회 내용을 표시해요.';
    },
  });
}

let stopAvailability = null;
let stopCatalog = null;
function connectAvailability() {
  stopAvailability?.();
  stopAvailability = subscribeRobotAvailability(receiveRobotAvailability);
}
window.addEventListener('pagehide', () => { autoReturn.suspend(); stopSimulator(); stopAvailability?.(); stopPreparation?.(); stopCatalog?.(); });
window.addEventListener('pageshow', event => { if (event.persisted) { autoReturn.resume(); connectCatalog(); if(simulationEnabled)watchSimulatedSession(); connectAvailability(); if (state.page === 'session') connectPreparation(); } });
app.innerHTML = '<main class="main"><h1>작품 정보를 불러오고 있어요…</h1></main>';
loadCatalog().then(async () => {
  let pending; try { pending=sessionStorage.getItem('arti-preparation'); } catch {}
  if (pending) {
    try {
      const session=await getSession(pending);
      if (session.status === 'calling') { state.session=session; state.mode=session.mode; state.selectedArtworkIds=[...session.artworkIds]; state.page='session'; history=['mode']; connectPreparation(); }
      else rememberPreparation(null);
    } catch { rememberPreparation(null); }
  }
  try{simulationEnabled=(await (await fetch('/api/test-mode')).json()).enabled===true;}catch{}
  if(simulationEnabled)watchSimulatedSession();
  render(); connectAvailability(); connectCatalog();
}).catch(() => {
  app.innerHTML = '<main class="main"><h1>로컬 서버 연결을 확인해 주세요</h1><p>프로젝트 폴더에서 python3 app.py를 실행한 뒤 다시 접속해 주세요.</p><a href="/">다시 시도하기</a></main>';
});

async function refreshAdminControls() {
  try {
    const response = await fetch('/api/auth/status');
    const data = response.ok ? await response.json() : {};
    const changed = adminAuthenticated !== (data.authenticated === true);
    adminAuthenticated = data.authenticated === true;
    if (changed && state.page === 'session') render();
  } catch { adminAuthenticated = false; }
  const controls = document.querySelector('.dev-controls');
  if (controls) controls.hidden = !adminAuthenticated;
}
window.addEventListener('focus', refreshAdminControls);
refreshAdminControls();
