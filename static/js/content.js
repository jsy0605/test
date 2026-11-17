// 안내 이미지·영상·오디오 파일을 static/media/에 넣고 src를 지정합니다.
// type: 'image' | 'video' | 'audio'
export const content = {
  exhibition: {
    eyebrow: 'WELCOME TO THE GALLERY',
    title: '갤러리 소개',
    description: '오늘의 전시와 공간의 이야기를 만나보세요.',
    media: { type: 'image', src: '/static/media/gallery-introduction.png', width: 1536, height: 1024, alt: 'Art I 갤러리 소개: 로봇 큐레이터와 함께 작품을 탐험하는 인터랙티브 갤러리. 자연·색채·추상 전시 주제와 음성 안내 관람 경험을 소개합니다.' },
    caption: '예술과 당신이 만나는 공간',
    text: '잠시 일상을 내려놓고, 당신의 시선이 머무는 작품을 만나보세요.',
  },
  usage: {
    eyebrow: 'MEET YOUR ART COMPANION',
    title: 'Art I 사용방법',
    description: '아티와 함께 관람하는 방법을 미리 알아보세요.',
    media: { type: 'image', src: '/static/media/arti-usage-notice.png', width: 1536, height: 1024, alt: '서비스 이용 시 주의사항: 로봇을 잡지 마세요. 역주행하지 마세요. 한 번에 한 사람만 이용해 주세요. 안전한 관람을 위해 협조해 주세요.' },
    caption: '아티와 함께, 세 단계면 충분해요',
    text: '관람 방법을 고르고, 만남 장소에서 등록한 뒤, 작품 이야기를 만나세요.',
  },
};
