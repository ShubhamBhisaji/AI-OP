/* eslint-disable no-undef */
export function addEvent(element, type, callback) {
  if (!element) {
    throw new Error('Element is null or undefined');
  }

  if (typeof callback !== 'function') {
    throw new Error('Callback must be a function');
  }

  if (typeof type !== 'string') {
    throw new Error('Type must be a string');
  }

  element.addEventListener(type, callback);
}

export function removeEvent(element, type) {
  if (!element) {
    throw new Error('Element is null or undefined');
  }

  element.removeEventListener(type, null);
}

export function storeLocalData(key, value) {
  if (!key || typeof key !== 'string') {
    throw new Error('Key must be a string');
  }

  if (typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Value must be an object');
  }

  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    console.error(error);
  }
}

export function getLocalData(key) {
  if (!key) {
    throw new Error('Key is null or undefined');
  }

  try {
    return JSON.parse(localStorage.getItem(key));
  } catch (error) {
    return null;
  }
}

export function clearLocalData() {
  try {
    localStorage.removeItem('user-data');
  } catch (error) {
    console.error(error);
  }
}

export function loadUserData() {
  try {
    return JSON.parse(localStorage.getItem('user-data'));
  } catch (error) {
    return null;
  }
}

export function saveUserData(data) {
  try {
    localStorage.setItem('user-data', JSON.stringify(data));
  } catch (error) {
    console.error(error);
  }
}

export function generateRandomString(min, max) {
  if (typeof min !== 'number' || typeof max !== 'number') {
    throw new Error('Minimum and maximum values must be numbers');
  }

  if (min >= max) {
    throw new Error('Minimum value must be less than maximum value');
  }

  return Math.random().toString(36).substr(2, max - min + 1);
}

export function generateRandomInt(min, max) {
  if (typeof min !== 'number' || typeof max !== 'number') {
    throw new Error('Minimum and maximum values must be numbers');
  }

  if (min >= max) {
    throw new Error('Minimum value must be less than maximum value');
  }

  return Math.floor(Math.random() * (max - min + 1)) + min;
}

export function convertTimeToEpoch(time) {
  if (typeof time !== 'string') {
    throw new Error('Time must be a string');
  }

  const regex = /(\d{4})-(\d{2})-(\d{2})\s(\d{2}):(\d{2})\s(\d{2})\s(\d{2})\.(\d{3})$/;
  const match = regex.exec(time);

  if (match) {
    const date = new Date(match[1], match[2] - 1, match[3], match[4], match[5], match[6], match[7], match[8]);

    return date.getTime() / 1000;
  } else {
    throw new Error('Invalid time format');
  }
}

export function convertEpochToTime(epoch) {
  if (typeof epoch !== 'number') {
    throw new Error('Epoch must be a number');
  }

  return new Date(epoch * 1000);
}

export function calculateDifferenceInMinutes(time1, time2) {
  if (typeof time1 !== 'string' || typeof time2 !== 'string') {
    throw new Error('Time must be a string');
  }

  const regex = /(\d{4})-(\d{2})-(\d{2})\s(\d{2}):(\d{2})\s(\d{2})\s(\d{2})\.(\d{3})$/;
  const match1 = regex.exec(time1);
  const match2 = regex.exec(time2);

  if (match1 && match2) {
    const date1 = new Date(match1[1], match1[2] - 1, match1[3], match1[4], match1[5], match1[6], match1[7], match1[8]);

    const date2 = new Date(match2[1], match2[2] - 1, match2[3], match2[4], match2[5], match2[6], match2[7], match2[8]);

    return Math.abs((date2 - date1) / (1000 * 60));
  } else {
    throw new Error('Invalid time format');
  }
}