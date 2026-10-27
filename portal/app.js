const ENDPOINT = '/api/v1/onboarding/start';

const OUTCOMES = {
  APROBADO: { title: 'Solicitud aprobada preliminarmente', tone: 'ok' },
  REQUIERE_INFO: { title: 'Necesitamos más información', tone: 'info' },
  ESCALADO: { title: 'Tu solicitud está en revisión', tone: 'info' },
  RECHAZADO: { title: 'No pudimos continuar en línea', tone: 'stop' },
};

const FIELD_ERRORS = {
  prospect_name: 'Ingresa tu nombre usando solo letras.',
  document_id: 'La cédula debe tener exactamente 10 dígitos.',
  product: 'Elige un producto.',
};

const form = document.querySelector('#onboarding-form');
const submit = document.querySelector('#submit');
const result = document.querySelector('#result');

function clearFeedback() {
  result.hidden = true;
  result.replaceChildren();
  result.removeAttribute('data-tone');
  for (const el of form.querySelectorAll('.field-error')) {
    el.hidden = true;
    el.textContent = '';
  }
  for (const input of form.elements) input.removeAttribute?.('aria-invalid');
}

function setBusy(busy) {
  submit.disabled = busy;
  submit.textContent = busy ? 'Enviando…' : 'Solicitar';
  form.setAttribute('aria-busy', String(busy));
}

const BULLET = /^\s*[-*•]\s+/;

// Renders message lines in order: consecutive bullet lines become one list.
function show(tone, title, lines = []) {
  result.dataset.tone = tone;
  const heading = document.createElement('h2');
  heading.textContent = title;
  result.append(heading);

  let list = null;
  for (const line of lines.filter((l) => l.trim())) {
    if (BULLET.test(line)) {
      if (!list) {
        list = document.createElement('ul');
        result.append(list);
      }
      const li = document.createElement('li');
      li.textContent = line.replace(BULLET, '');
      list.append(li);
    } else {
      list = null;
      const p = document.createElement('p');
      p.textContent = line.trim();
      result.append(p);
    }
  }
  result.hidden = false;
  result.focus();
}

function showFieldErrors(details) {
  const fields = new Set(details.map((d) => d.field));
  for (const field of fields) {
    const slot = document.querySelector(`#${field}-error`);
    if (!slot || !(field in FIELD_ERRORS)) continue;
    slot.textContent = FIELD_ERRORS[field];
    slot.hidden = false;
    form.elements[field]?.setAttribute('aria-invalid', 'true');
  }
  form.querySelector('[aria-invalid="true"]')?.focus();
}

function showOutcome(body) {
  const outcome = OUTCOMES[body.decision] ?? OUTCOMES.REQUIERE_INFO;
  // The server guarantees the message already names every required document.
  show(outcome.tone, outcome.title, body.customer_message.split('\n'));
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearFeedback();
  setBusy(true);

  const payload = Object.fromEntries(new FormData(form));
  payload.prospect_name = payload.prospect_name.trim();

  try {
    const response = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));

    if (response.ok) showOutcome(body);
    else if (response.status === 422 && Array.isArray(body.details)) showFieldErrors(body.details);
    else if (response.status === 429) show('stop', 'Demasiadas solicitudes', ['Espera un momento e inténtalo de nuevo.']);
    else show('stop', 'No pudimos procesar tu solicitud', ['Inténtalo de nuevo en unos minutos.']);
  } catch {
    show('stop', 'Sin conexión', ['No pudimos conectar con el banco. Revisa tu conexión e inténtalo de nuevo.']);
  } finally {
    setBusy(false);
  }
});

for (const button of document.querySelectorAll('[data-document]')) {
  button.addEventListener('click', () => {
    form.elements.document_id.value = button.dataset.document;
    if (!form.elements.prospect_name.value) form.elements.prospect_name.value = 'Juan Perez';
    form.elements.document_id.focus();
  });
}
