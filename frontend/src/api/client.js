import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000';

const client = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

client.interceptors.request.use(config => {
  const initData = window.Telegram?.WebApp?.initData;
  if (initData) config.headers['X-Telegram-Init-Data'] = initData;
  return config;
});

export const DATA_CHANGED_EVENT = 'foshoo:data-changed';
client.interceptors.response.use(response => {
  const method = response.config.method?.toLowerCase();
  if (['post', 'put', 'patch', 'delete'].includes(method) && response.config.url !== '/api/assistant/chat') {
    window.dispatchEvent(new Event(DATA_CHANGED_EVENT));
  }
  return response;
});

export async function uploadAfisha(file) {
  const form = new FormData();
  form.append('file', file);
  return client.post('/api/afisha/upload', form, { headers: { 'Content-Type': undefined } });
}

export const assistantApi = {
  async chat({ userId, username, sessionId, message, history }) {
    const { data } = await client.post('/api/assistant/chat', {
      user_id: userId,
      username: username || '',
      session_id: sessionId,
      message,
      history,
    });
    return data;
  },
  async execute({ userId, actionToken }) {
    const { data } = await client.post('/api/assistant/execute', {
      user_id: userId,
      action_token: actionToken,
    });
    return data;
  },
  async hints() {
    const { data } = await client.get('/api/assistant/hints');
    return data.hints || [];
  },
};

export default client;
