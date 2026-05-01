package com.server.faceservice.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

@Configuration
public class WebsocketThreadPoolConfig {

    /**
     * 定义WebSocket相关的线程池（重连、消息处理共用）
     */
    @Bean(name = "websocketExecutor")
    public ExecutorService websocketExecutor() {
        // 核心线程数：CPU核心数（根据业务调整）
        int corePoolSize = Runtime.getRuntime().availableProcessors();
        // 最大线程数：核心线程数*2（避免线程过多导致资源耗尽）
        int maxPoolSize = corePoolSize * 2;
        // 空闲线程存活时间：60秒
        long keepAliveTime = 60L;
        // 任务队列：容量1024（避免队列过大导致OOM）
        BlockingQueue<Runnable> workQueue = new LinkedBlockingQueue<>(1024);
        // 线程工厂：指定线程名，便于日志排查
        ThreadFactory threadFactory = new ThreadFactory() {
            private final AtomicInteger threadNum = new AtomicInteger(1);
            @Override
            public Thread newThread(Runnable r) {
                Thread thread = new Thread(r, "websocket-pool-" + threadNum.getAndIncrement());
                thread.setDaemon(true); // 守护线程，随主线程退出
                return thread;
            }
        };
        // 拒绝策略：当队列满时，让提交任务的线程执行（避免任务丢失）
        RejectedExecutionHandler handler = new ThreadPoolExecutor.CallerRunsPolicy();

        return new ThreadPoolExecutor(
                corePoolSize,
                maxPoolSize,
                keepAliveTime,
                TimeUnit.SECONDS,
                workQueue,
                threadFactory,
                handler
        );
    }
}