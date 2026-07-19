import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000';

const client = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

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
