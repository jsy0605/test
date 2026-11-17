// 초기 데이터는 data/catalog.json → SQLite → Flask API 순서로 전달됩니다.
export const artworks = [];
export const courses = [];

let catalogSignature = '';
export async function loadCatalog({signal} = {}) {
  const response = await fetch('/api/catalog', {cache: 'no-store', signal});
  if (!response.ok) throw new Error('작품 정보를 불러오지 못했습니다.');
  const data = await response.json();
  const signature = JSON.stringify(data);
  if (signature === catalogSignature) return false;
  // ROS/관람 기록의 내부 ID는 유지하고, 표시용 작품 코드와 이미지는 DB에서 읽습니다.
  artworks.splice(0, artworks.length, ...data.artworks.map(art => ({
    ...art, id: `art-${String(art.artwork_index).padStart(2, '0')}`,
    artist: art.artist_name, number: art.artwork_index,
  })));
  courses.splice(0, courses.length, ...(data.courses || []));
  catalogSignature = signature;
  return true;
}

export const getArtwork = id => artworks.find(art => art.id === id);
export const artImage = art => art.image_path;
