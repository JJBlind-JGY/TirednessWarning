// src/utils/sign.js
import md5 from "js-md5";

/**
 * 生成带签名的请求参数
 * @param {Object} params 请求参数
 * @param {String} secretKey 前后端约定密钥
 * @returns {Object} 新参数（含 sign, timestamp, nonce）
 */
export function generateSignedParams(params = {}, secretKey) {
  // 1️⃣ 时间戳 & 随机字符串
  const timestamp = Date.now();
  const nonce = Math.random().toString(36).substring(2, 10);

  // 2️⃣ 合并参数
  const allParams = { ...params, timestamp, nonce };

  // 3️⃣ 按 key 升序拼接字符串
  const sortedKeys = Object.keys(allParams).sort();
  const queryStr = sortedKeys.map(k => `${k}=${allParams[k]}`).join("&");

  // 4️⃣ 拼接密钥并计算 MD5
  const raw = `${queryStr}&secretKey=${secretKey}`;
  const sign = md5(raw).toUpperCase();

  return { ...allParams, sign };
}
