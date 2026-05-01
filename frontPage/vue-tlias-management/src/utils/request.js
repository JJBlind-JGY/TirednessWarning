import axios from "axios";
import md5 from "js-md5";
import { ElMessage } from "element-plus";
import router from "../router";
import { generateSignedParams } from "./sign.js";

//  密钥与后端一致
const SECRET_KEY = "MySecretKey123";

const request = axios.create({
  baseURL: "/api",
  timeout: 600000
});

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    const loginUser = JSON.parse(localStorage.getItem("loginUser"));

    if (loginUser && loginUser.token) {
      config.headers.token = loginUser.token;
    }

    // 对 POST/PUT/GET 等请求进行签名
    if (config.method === "post" || config.method === "put") {
      config.data = generateSignedParams(config.data || {}, SECRET_KEY);
    } else if (config.method === "get") {
      config.params = generateSignedParams(config.params || {}, SECRET_KEY);
    }

    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截器
request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response && error.response.status === 401) {
      ElMessage.error("登录超时，请重新登录");
      router.push("/login");
    } else {
      ElMessage.error("接口访问异常");
    }
    return Promise.reject(error);
  }
);

export default request;
