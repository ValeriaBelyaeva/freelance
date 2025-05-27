def check_on_line(point1, point2, point3, accuracy= 90.0):
    """
    checks whether point 2 lies on the line drawn through points 1 and 3
    two vectors are constructed from the central point. The angle alpha
    is found from the scalar product formulas x1*x2+y1*y2 = |a|*|b|*cos(alfa). 
    alpha should be equal to 180, taking into account the error

    :param point1: tuple of three variables (X coordinate, Y coordinate, Z coordinate)
    :param point2: central point. tuple of three variables (X coordinate, Y coordinate, Z coordinate)
    :param point3: tuple of three variables (X coordinate, Y coordinate, Z coordinate)
    :param accuracy: calculation error in degrees (angle p1p2p3+-accuracy=180)
    :return: bool on_lint - does point 2 lie on the line drawn through points 1 and 3
    """

    vector21 = (point1[0]-point2[0], point1[1]-point2[1], point1[2]-point2[2])
    len_vector21 = (vector21[0]**2 + vector21[1]**2 + vector21[2]**2) ** 0.5

    vector23 = (point3[0]-point2[0], point3[1]-point2[1], point3[2]-point2[2])
    len_vector23 = (vector23[0]**2 + vector23[1]**2 + vector23[2]**2) ** 0.5

    cos_alfa = (vector21[0]*vector23[0] + vector21[1]*vector23[1] + vector21[2]*vector23[2]) / (len_vector21 * len_vector23)
    eps = 0.00001 # the error of trigonometric functions

    return 180-accuracy <= math.degrees(math.acos(cos_alfa))+eps <= 180+accuracy
