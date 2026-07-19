async function ksfFetch(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json')
    ? await response.json()
    : { error: await response.text() };
  if (!response.ok) {
    throw new Error(payload.error || `Erreur HTTP ${response.status}`);
  }
  return payload;
}

function ksfError(error) {
  return error instanceof Error ? error.message : 'Erreur inconnue';
}
