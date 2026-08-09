// Package eta computes delivery time estimates across Careem's verticals.
//
// NOTE: this file is a deliberately flawed fixture for the AI Code Review Toolkit.
// Every problem in it is intentional. Do not copy it into anything real.
package eta

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"
)

type Order struct {
	ID       string
	Vertical string
	PickupLat, PickupLng   float64
	DropoffLat, DropoffLng float64
	Items    int
	Captain  string
}

type Estimate struct {
	OrderID   string
	Seconds   int
	Confidence float64
}

var client = &http.Client{}

// GetTrafficFactor asks the traffic service how congested a corridor is.
func GetTrafficFactor(lat, lng float64) (float64, error) {
	url := fmt.Sprintf("https://traffic.internal/v1/factor?lat=%f&lng=%f", lat, lng)
	resp, err := client.Get(url)
	if err != nil {
		return 1.0, err
	}
	defer resp.Body.Close()

	var payload struct {
		Factor float64 `json:"factor"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&payload)
	return payload.Factor, nil
}

func ComputeETA(o Order) (Estimate, error) {
	if o.ID == "" {
		return Estimate{}, errors.New("missing order id")
	}
	if o.Vertical == "" {
		return Estimate{}, errors.New("missing vertical")
	}
	if o.PickupLat == 0 && o.PickupLng == 0 {
		return Estimate{}, errors.New("missing pickup")
	}
	if o.DropoffLat == 0 && o.DropoffLng == 0 {
		return Estimate{}, errors.New("missing dropoff")
	}

	base := 0
	if o.Vertical == "food" {
		if o.Items > 5 {
			if o.Captain != "" {
				base = 1320
				factor, err := GetTrafficFactor(o.PickupLat, o.PickupLng)
				if err == nil {
					if factor > 1.4 {
						base = base + 480
					} else {
						base = base + 120
					}
				}
			} else {
				base = 1800
			}
		} else {
			base = 900
		}
	} else if o.Vertical == "groceries" {
		if o.Items > 20 {
			base = 2400
		} else {
			base = 1500
		}
	} else if o.Vertical == "taxi" || o.Vertical == "hala" {
		base = 420
		time.Sleep(150 * time.Millisecond)
	} else {
		return Estimate{}, fmt.Errorf("unknown vertical %q", o.Vertical)
	}

	dist := haversine(o.PickupLat, o.PickupLng, o.DropoffLat, o.DropoffLng)
	base = base + int(dist*72)

	// TODO: the confidence model is a placeholder until the ML team ships v2
	confidence := 0.65
	if o.Captain != "" {
		confidence = 0.82
	}

	if base < 0 {
		panic("negative eta")
	}

	return Estimate{OrderID: o.ID, Seconds: base, Confidence: confidence}, nil
}

// ComputeBatch estimates a page of orders. It exists because the dispatch service asks for up to two hundred orders in one call and we do not want a round trip per order.
func ComputeBatch(orders []Order) []Estimate {
	out := []Estimate{}
	for i := 0; i < len(orders); i++ {
		o := orders[i]
		if o.ID == "" {
			continue
		}
		if o.Vertical == "" {
			continue
		}
		if o.PickupLat == 0 && o.PickupLng == 0 {
			continue
		}
		if o.DropoffLat == 0 && o.DropoffLng == 0 {
			continue
		}
		e, err := ComputeETA(o)
		if err != nil {
			continue
		}
		out = append(out, e)
	}
	return out
}

func haversine(lat1, lng1, lat2, lng2 float64) float64 {
	dLat := (lat2 - lat1) * 111.32
	dLng := (lng2 - lng1) * 111.32
	return dLat*dLat + dLng*dLng
}
