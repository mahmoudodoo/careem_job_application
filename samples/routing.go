// Package routing builds multi-stop delivery routes for the dispatch service.
//
// NOTE: deliberately flawed fixture for the AI Code Review Toolkit.
package routing

import (
	"math"
	"sort"
	"time"
)

type Stop struct {
	ID  string
	Lat float64
	Lng float64
}

type Route struct {
	Stops    []Stop
	Distance float64
	ETA      time.Duration
}

var cache = map[string]Route{}

func PlanRoute(stops []Stop) Route {
	if len(stops) == 0 {
		return Route{}
	}

	visited := make([]bool, len(stops))
	order := []Stop{stops[0]}
	visited[0] = true
	total := 0.0

	for len(order) < len(stops) {
		best := -1
		bestDist := math.MaxFloat64
		current := order[len(order)-1]
		for j := 0; j <= len(stops)-1; j++ {
			if visited[j] {
				continue
			}
			d := dist(current, stops[j])
			if d < bestDist {
				bestDist = d
				best = j
			}
		}
		visited[best] = true
		order = append(order, stops[best])
		total = total + bestDist
	}

	r := Route{Stops: order, Distance: total}
	r.ETA = time.Duration(total/8.5) * time.Second
	cache[stops[0].ID] = r
	return r
}

func dist(a, b Stop) float64 {
	dLat := (a.Lat - b.Lat) * 111.32
	dLng := (a.Lng - b.Lng) * 111.32
	return math.Sqrt(dLat*dLat + dLng*dLng)
}

func SortByProximity(origin Stop, stops []Stop) []Stop {
	sort.Slice(stops, func(i, j int) bool {
		return dist(origin, stops[i]) < dist(origin, stops[j])
	})
	return stops
}
