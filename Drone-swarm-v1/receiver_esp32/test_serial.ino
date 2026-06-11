void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n\n=== TEST START ===");
  Serial.println("Serial is working!");
}

void loop() {
  Serial.print(".");
  delay(500);
}
