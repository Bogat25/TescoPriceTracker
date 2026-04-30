FULL_PRODUCT_QUERY = """
query GetProduct($tpnc: String) {
  product(tpnc: $tpnc) {
    id
    tpnb
    gtin
    barcode
    title
    shortDescription
    brandName
    subBrand
    defaultImageUrl
    productType
    isNew
    isForSale
    status
    sellType
    superDepartmentName
    superDepartmentId
    departmentName
    departmentId
    aisleName
    aisleId
    shelfName
    shelfId
    primaryTaxonomyNode {
      id
      name
    }
    manufacturer
    manufacturerAddress
    distributorAddress
    importerAddress
    returnTo
    depositAmount
    maxQuantityAllowed
    maxWeight
    minWeight
    storageClassification
    displayImages {
      url
      default
    }
    details {
      packSize {
        value
        units
      }
      ingredients
      allergens
      nutrition {
        tableType
        rows {
          label
          valuePer100
          valuePerServing
        }
      }
      gda {
        values {
          name
          percent
          rating
          value
        }
      }
      storage
      cookingInstructions {
        oven {
          chilled {
            time
            temperature {
              value
            }
            instructions
          }
          frozen {
            time
            temperature {
              value
            }
            instructions
          }
        }
        microwave {
          chilled {
            detail
          }
          frozen {
            detail
          }
        }
        otherInstructions
        cookingGuidelines
        cookingPrecautions
      }
      preparationAndUsage
      preparationGuidelines
      marketing
      productMarketing
      brandMarketing
      manufacturerMarketing
      originInformation
      recyclingInfo
      netContents
      drainedWeight
      safetyWarning
      lowerAgeLimit
      upperAgeLimit
      healthmark
      numberOfUses
      freezingInstructions
      alcohol
      dosage
      directions
      features
      healthClaims
      nutritionalClaims
      boxContents
      legalNotice
      shelfLifeInfo
      otherInformation
      warnings
      additives
      dietaryInfo
      intoleranceInfo
      hfss
      specifications
      components
    }
    icons {
      label
      imageUrl
    }
    shelfLife
    reviews {
      stats {
        overallRating
        noOfReviews
        overallRatingRange
        ratingsDistribution {
          one
          two
          three
          four
          five
        }
      }
    }
    price {
      actual
      unitPrice
      unitOfMeasure
    }
    promotions {
      id
      startDate
      endDate
      description
      attributes
      price {
        afterDiscount
      }
    }
  }
}
"""

PRICE_ONLY_QUERY = """
query GetProductPrice($tpnc: String) {
  product(tpnc: $tpnc) {
    id
    price {
      actual
      unitPrice
      unitOfMeasure
    }
    promotions {
      id
      startDate
      endDate
      description
      attributes
      price {
        afterDiscount
      }
    }
  }
}
"""
