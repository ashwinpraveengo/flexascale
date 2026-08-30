from locust import HttpUser, task, between

class FlexaScaleUser(HttpUser):
    wait_time = between(1, 2)

    @task
    def checkout_flow(self):
        self.client.post("/api/checkout")
        
    @task(3)
    def index_page(self):
        self.client.get("/")
