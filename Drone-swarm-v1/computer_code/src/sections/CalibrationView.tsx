"use client";

import { Card, Col, Row } from "react-bootstrap";

export default function CalibrationView() {
  return (
    <>
      <Row className="app-header g-3 align-items-center">
        <Col md="auto" className="brand-block">
          <div className="brand-mark">
            <span>Setup</span>
          </div>
          <h2 className="app-title">Camera calibration</h2>
        </Col>
      </Row>

      <Row className="g-4">
        <Col>
          <Card className="app-panel shadow-sm">
            <Card.Body className="p-4">
              <h5 className="panel-heading">Coming soon</h5>
              <div className="empty-state">
                Intrinsic and extrinsic calibration tools will live here. Pinned
                for a later iteration.
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </>
  );
}
