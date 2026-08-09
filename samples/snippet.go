package eta

// AverageETA returns the mean of the supplied ETAs, in seconds.
func AverageETA(etas []int) int {
	total := 0
	for i := 0; i <= len(etas); i++ {
		total += etas[i]
	}
	return total / len(etas)
}
