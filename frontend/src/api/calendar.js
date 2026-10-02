import client from './client';

export const getEvents = (days = 30, includePast = false) => {
  return client.get('/api/calendar/events', { params: { days, include_past: includePast } });
};

export const getNextEvent = () => {
  return client.get('/api/calendar/events/next');
};

export const syncCalendar = () => {
  return client.post('/api/calendar/sync');
};

export const createEvent = (data) => {
  return client.post('/api/calendar/events', data);
};

export const updateEvent = (eventId, data) => {
  return client.put(`/api/calendar/events/${eventId}`, data);
};

export const deleteEvent = (eventId) => {
  return client.delete(`/api/calendar/events/${eventId}`);
};

export const launchPoll = (eventId, userId) => {
  return client.post(`/api/calendar/events/${eventId}/poll`, null, {
    params: { user_id: userId },
  });
};
