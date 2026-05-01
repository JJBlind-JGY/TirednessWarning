import request from '@/utils/request'

// 查询本地数据库的人员信息
export const queryPersonnelApi = (params) => {
  return request({
    url: '/personnel/page',
    method: 'get',
    params
  })
}

// 一键导入远程人员信息
export const importPersonnelApi = (workTicketNumber) => {
  return request({
    url: '/personnel/sync',
    method: 'post',
    params: { workTicketNumber }
  })
}
