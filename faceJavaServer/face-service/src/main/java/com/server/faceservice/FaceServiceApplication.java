package com.server.faceservice;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;

@SpringBootApplication(exclude = {DataSourceAutoConfiguration.class})
public class FaceServiceApplication {

	public static void main(String[] args) {
		SpringApplication.run(FaceServiceApplication.class, args);
	}

}
