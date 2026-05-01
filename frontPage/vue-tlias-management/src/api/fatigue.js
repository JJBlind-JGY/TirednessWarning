import request from "@/utils/request";

export const getEegData = (dept) =>  request.get('/eeg', dept);